"""Works out who the diarized speakers are from what they say. The audio only
tells us "Speaker 2 is a different voice from Speaker 1"; the words often say
the rest -- "Hi, I'm Jane Doe", a roll call, a chair saying "thank you,
Commissioner Lee" right before a new voice answers. One structured LLM call
reads the transcript and reports, per speaker, a name only where the text
supports it, with a confidence and the quote it relied on.

High-confidence names are applied automatically (the user can still rename);
medium ones are offered as one-click suggestions; anything weaker is dropped.
See pipeline.py's audio branch for how the result is used."""

from . import transform

CONFIDENCES = ("high", "medium", "low", "none")
MAX_NAME_CHARS = 80
# The prompt gets the whole transcript (names can come up anywhere), but a
# long meeting's long turns are trimmed to fit this many characters.
MAX_TRANSCRIPT_CHARS = 150_000

SYSTEM_PROMPT = """You are identifying who each speaker in a diarized transcript is, using ONLY what the transcript text says.

Speakers are labelled "Speaker 1", "Speaker 2", ... (a diarization engine separated the voices; the labels carry no meaning). Evidence you may use:
- Self-introductions: "I'm Jane Doe", "this is Mark from Operations", "Jane Doe, present" in a roll call. -> high.
- Being addressed by name and then answering: a speaker says "Thank you, Chair Smith" or "Mark, what do you think?" and the next DIFFERENT speaker responds. -> high if the reply confirms it ("Thanks, Jane" / "Happy to answer"), otherwise medium.
- Being introduced right before speaking: "I'll turn it over to Dr. Lee" followed by a new speaker. -> medium, high if the new speaker acknowledges it.
- Consistent role + surname references across the transcript (e.g. several people say "Chairman Walker" to the same speaker). -> medium to high.

Rules:
- Never guess from gender, accent, topic or style. If the text doesn't support a name, return an empty name and confidence "none".
- Beware who is being talked ABOUT: "Commissioner Lee said earlier..." names a third person, not the speaker.
- Give the name as fully as the transcript supports it ("Jane Doe"); if only a title and surname are known, use that ("Chair Smith"). No extra words, no quotes.
- Never give the same name to two different speakers.
- evidence: a short verbatim quote (under 25 words) from the transcript that supports the name, with its timestamp like [123s]. Empty if no name.
- Return one entry for every speaker label you were given."""

SCHEMA = transform._object(
    {
        "speakers": transform._array(
            transform._object(
                {
                    "label": transform.STRING,
                    "name": transform.STRING,
                    "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                    "evidence": transform.STRING,
                }
            )
        )
    }
)


def _condensed_transcript(segments: list[dict]) -> str:
    """The transcript in the usual "[12s] Speaker 1: ..." form, with long
    turns trimmed (keeping the start and end, where introductions and
    thank-yous live) just enough to fit MAX_TRANSCRIPT_CHARS."""
    text = ""
    for limit in (None, 600, 300, 150):
        lines = []
        for s in segments:
            body = s["text"]
            if limit and len(body) > limit:
                head = int(limit * 0.7)
                body = f"{body[:head].rstrip()} ... {body[-(limit - head):].lstrip()}"
            lines.append(f"[{s['start_ts']:.0f}s] {s['speaker']}: {body}")
        text = "\n".join(lines)
        if len(text) <= MAX_TRANSCRIPT_CHARS:
            return text
    return text[:MAX_TRANSCRIPT_CHARS]


def _clean_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not name or len(name) > MAX_NAME_CHARS or not name.isprintable():
        return ""
    return name


def identify(segments: list[dict], speakers: list[str]) -> dict[str, dict]:
    """{label: {"name", "confidence" ("high"|"medium"), "evidence"}} for the
    speakers the transcript names with at least medium confidence. Raises
    whatever the LLM call raises -- the caller decides what a failure costs."""
    data = transform._call_json(
        SYSTEM_PROMPT,
        f"SPEAKER LABELS: {', '.join(speakers)}\n\nTRANSCRIPT:\n{_condensed_transcript(segments)}",
        "submit_speaker_identification",
        SCHEMA,
    )
    found: dict[str, dict] = {}
    for entry in data.get("speakers", []):
        label = entry.get("label")
        name = _clean_name(entry.get("name", ""))
        confidence = entry.get("confidence")
        if label not in speakers or not name or confidence not in ("high", "medium") or label in found:
            continue
        found[label] = {"name": name, "confidence": confidence, "evidence": (entry.get("evidence") or "").strip()[:300]}

    # Two voices can't both be the same person; if the model said so, it has
    # confused them, so trust neither enough to apply it.
    by_name: dict[str, list[str]] = {}
    for label, hint in found.items():
        by_name.setdefault(hint["name"].casefold(), []).append(label)
    for labels in by_name.values():
        if len(labels) > 1:
            for label in labels:
                found[label]["confidence"] = "medium"
    return found


def split_for_use(found: dict[str, dict], apply_at: str = "high") -> tuple[dict[str, str], dict[str, dict]]:
    """(names to apply now, hints to persist). Names at `apply_at` confidence
    or better are applied ("high" only, by default; "medium" also fills in the
    medium ones); every hint is kept, with `applied` saying which, so the
    viewer can show the evidence or offer a suggestion."""
    applied = ("high", "medium") if apply_at == "medium" else ("high",)
    names = {label: h["name"] for label, h in found.items() if h["confidence"] in applied}
    hints = {label: {**h, "applied": label in names} for label, h in found.items()}
    return names, hints
