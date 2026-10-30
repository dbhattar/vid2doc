"""What a video job turns the video into, beyond the full document that
compose.compose_document produces. Every transformation here returns the same
`sections` shape (a list of {heading, blocks: [{type: "paragraph", text}]})
that pipeline._finalize_document already renders, so everything downstream --
document.md/docx/pdf, chat, share, Drive -- works unchanged. Paragraph text may
contain markdown links and "- " bullets (see assemble.py's inline handling).

All of these are text-only: they work from the transcript, not frames."""

import json
import logging
import math
import os
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..config import settings
from ..exceptions import PipelineError
from ..youtube import is_youtube_url
from . import compose, web_research

logger = logging.getLogger(__name__)

TRANSFORMATIONS = ("document", "notes", "study_guide", "research")

NOTES_MAX_TOPICS = 4
NOTES_MAX_LINKS = 8
RESEARCH_MAX_TOPICS = 6
# Upper bound on what a user can confirm/add at topic review.
RESEARCH_MAX_REVIEWED_TOPICS = 8
RESEARCH_TOPICS_PER_WINDOW = 3
# How much of what the video said about a topic is passed to web research.
RESEARCH_CONTEXT_CHARS = 1500


TITLE_PREFIX = {"notes": "Notes", "study_guide": "Study guide", "research": "Research"}


def validate_options(transformation: str, make_public: bool) -> str | None:
    """An error message for an invalid submit-time combination, else None."""
    if transformation not in TRANSFORMATIONS:
        return f"Unknown transformation '{transformation}'. Allowed: {list(TRANSFORMATIONS)}"
    if transformation != "document" and make_public:
        return "Only full documents can be made public."
    return None


# --- LLM plumbing -----------------------------------------------------------


def _call_json(system: str, user: str, name: str, schema: dict) -> dict:
    """One structured-output call on whichever provider LLM_PROVIDER names.
    `schema` must satisfy OpenAI strict mode (every property required,
    additionalProperties false); Anthropic gets it as a forced tool."""
    if settings.LLM_PROVIDER == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PipelineError("OPENAI_API_KEY is not set")
        response = openai.OpenAI(api_key=api_key).chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        )
        return json.loads(response.choices[0].message.content)

    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PipelineError("ANTHROPIC_API_KEY is not set")
    response = anthropic.Anthropic(api_key=api_key).messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=system,
        tools=[{"name": name, "description": f"Submit the {name}.", "input_schema": schema}],
        tool_choice={"type": "tool", "name": name},
        messages=[{"role": "user", "content": user}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    return {}


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _array(items: dict) -> dict:
    return {"type": "array", "items": items}


STRING = {"type": "string"}


# --- shared helpers ---------------------------------------------------------


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "text": text, "ref": 0, "caption": ""}


def _section(heading: str, paragraphs: list[str]) -> dict:
    return {"heading": heading, "blocks": [_paragraph(p) for p in paragraphs if p.strip()]}


def _link(title: str, url: str) -> str:
    return f"[{title.replace('[', '(').replace(']', ')')}]({url})"


def _format_clock(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def timestamp_ref(seconds, source_url: str | None, media_end: float) -> str:
    """A reference to a moment in the video. The model only ever supplies the
    number: this builds the link, so a YouTube URL can't be hallucinated.
    YouTube sources deep-link (?t=); uploads have nothing to link to, so they
    get a plain (mm:ss) marker. Empty if the time is unusable."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(seconds) or seconds < 0 or seconds > media_end:
        return ""
    label = _format_clock(seconds)
    if source_url and is_youtube_url(source_url):
        parts = urlparse(source_url)
        query = dict(parse_qsl(parts.query))
        query["t"] = f"{int(seconds)}s"
        return _link(label, urlunparse(parts._replace(query=urlencode(query))))
    return f"({label})"


def _media_end(segments: list[dict]) -> float:
    return max((s.get("end_ts", s.get("start_ts", 0)) for s in segments), default=0)


def _transcript_text(segments: list[dict]) -> str:
    return compose._window_text(segments)


# --- notes ------------------------------------------------------------------

NOTES_SYSTEM_PROMPT = """You are turning a slice of a video's transcript into concise study-friendly notes.

Group the notes under short, specific headings. Under each heading write brief bullet points -- fragments or single sentences, never paragraphs -- that capture the facts, decisions, definitions, numbers and takeaways. Drop filler, repetition and small talk. For each point, set start_seconds to the [Ns] timestamp at the start of the transcript line it comes from, so the reader can jump to it. Use only information in the transcript."""

NOTES_SCHEMA = _object(
    {"sections": _array(_object({"heading": STRING, "points": _array(_object({"text": STRING, "start_seconds": {"type": "number"}}))}))}
)


def compose_notes(
    segments: list[dict], source_url: str | None, on_stage: Callable[[str], None]
) -> tuple[list[dict], list[str]]:
    media_end = _media_end(segments)
    sections: list[dict] = []
    title_headings: list[str] = []
    for window in compose._make_windows(segments):
        data = _call_json(NOTES_SYSTEM_PROMPT, f"TRANSCRIPT:\n{_transcript_text(window)}", "submit_notes", NOTES_SCHEMA)
        for raw in data.get("sections", []):
            bullets = []
            for point in raw.get("points", []):
                ref = timestamp_ref(point.get("start_seconds"), source_url, media_end)
                bullets.append(f"- {point['text'].strip()} {ref}".rstrip())
            if bullets:
                sections.append(_section(raw["heading"], bullets))
                title_headings.append(raw["heading"])

    if sections and web_research.available():
        on_stage("researching")
        links = _further_reading(sections[:NOTES_MAX_TOPICS])
        if links:
            sections.append(_section("Further reading", [f"- {_link(l['title'], l['url'])}" for l in links]))
    return sections, title_headings


def _further_reading(sections: list[dict]) -> list[dict]:
    """External links for the notes' leading topics. Best effort: a failed
    search just means fewer links, never a failed job."""
    links: dict[str, dict] = {}
    for section in sections:
        context = "\n".join(b["text"] for b in section["blocks"])[:RESEARCH_CONTEXT_CHARS]
        try:
            result = web_research.research_topic(section["heading"], context)
        except Exception:
            logger.exception("Further-reading search failed for %r", section["heading"])
            continue
        for link in result["links"]:
            links.setdefault(link["url"], link)
    return list(links.values())[:NOTES_MAX_LINKS]


# --- study guide ------------------------------------------------------------

STUDY_SYSTEM_PROMPT = """You are writing a study guide from a video's transcript (or, when given several partial study guides in JSON, merging them into one for the whole video -- deduplicate, keep the best entries, and keep the order the material was taught in).

Produce: a short summary paragraph; 3-6 learning objectives ("After this you can ..."); the key concepts, each with a clear definition in plain language; and 5-10 review questions with concise answers that test understanding rather than recall of wording. Use only information in the transcript."""

STUDY_SCHEMA = _object(
    {
        "summary": STRING,
        "objectives": _array(STRING),
        "concepts": _array(_object({"term": STRING, "definition": STRING})),
        "questions": _array(_object({"question": STRING, "answer": STRING})),
    }
)


def compose_study_guide(segments: list[dict]) -> tuple[list[dict], list[str]]:
    windows = compose._make_windows(segments)
    partials = [
        _call_json(STUDY_SYSTEM_PROMPT, f"TRANSCRIPT:\n{_transcript_text(w)}", "submit_study_guide", STUDY_SCHEMA)
        for w in windows
    ]
    guide = partials[0] if len(partials) == 1 else _call_json(
        STUDY_SYSTEM_PROMPT, f"PARTIAL STUDY GUIDES:\n{json.dumps(partials)}", "submit_study_guide", STUDY_SCHEMA
    )
    sections = [
        _section("Summary", [guide.get("summary", "")]),
        _section("Learning objectives", [f"- {o}" for o in guide.get("objectives", [])]),
        _section("Key concepts", [f"- **{c['term']}**: {c['definition']}" for c in guide.get("concepts", [])]),
        _section(
            "Review questions",
            [f"{i}. {q['question']}\n   Answer: {q['answer']}" for i, q in enumerate(guide.get("questions", []), 1)],
        ),
    ]
    return sections, [c["term"] for c in guide.get("concepts", [])]


# --- research ---------------------------------------------------------------

TOPICS_SYSTEM_PROMPT = f"""You are picking topics worth researching on the web from a slice of a video's transcript: specific claims, technologies, people, events, studies or concepts where outside context would genuinely add something. Return at most {RESEARCH_TOPICS_PER_WINDOW}, most valuable first, each with a short label and a sentence or two on what the video says about it. Return none if nothing is worth researching."""

TOPICS_SCHEMA = _object({"topics": _array(_object({"topic": STRING, "context": STRING}))})


def extract_research_topics(segments: list[dict]) -> list[dict]:
    """The topics worth researching, as [{topic, context}] -- the cheap LLM
    half of research, split out so a job can pause here for the user to
    confirm/edit/add topics before any paid web search runs."""
    topics: list[dict] = []
    for window in compose._make_windows(segments):
        data = _call_json(TOPICS_SYSTEM_PROMPT, f"TRANSCRIPT:\n{_transcript_text(window)}", "submit_topics", TOPICS_SCHEMA)
        topics.extend(data.get("topics", [])[:RESEARCH_TOPICS_PER_WINDOW])
    seen, unique = set(), []
    for t in topics:
        key = t["topic"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(t)
    unique = unique[:RESEARCH_MAX_TOPICS]
    if not unique:
        raise PipelineError("Nothing in this video was specific enough to research.")
    return unique


def compose_research(
    segments: list[dict], on_stage: Callable[[str], None], topics: list[dict] | None = None
) -> tuple[list[dict], list[str]]:
    """`topics` is the user-confirmed list when the job paused for topic
    review; otherwise topics are picked automatically."""
    if not web_research.available():
        raise PipelineError("Research needs web search, but OPENAI_API_KEY is not set.")

    unique = topics if topics is not None else extract_research_topics(segments)

    on_stage("researching")
    sections = [_section("Overview", [compose.generate_summary(segments)])]
    for t in unique:
        context = t.get("context", "").strip()
        try:
            result = web_research.research_topic(t["topic"], context[:RESEARCH_CONTEXT_CHARS])
        except Exception:
            logger.exception("Research failed for %r", t["topic"])
            continue
        # A topic the user added themselves has no transcript context.
        paragraphs = ([f"From the video: {context}"] if context else []) + [result["summary"]]
        if result["links"]:
            paragraphs.append("Sources:\n" + "\n".join(f"- {_link(l['title'], l['url'])}" for l in result["links"]))
        sections.append(_section(t["topic"], paragraphs))
    if len(sections) == 1:
        raise PipelineError("Web research failed for every topic -- please try again.")
    return sections, [s["heading"] for s in sections[1:]]


# --- entry point ------------------------------------------------------------


def run(
    transformation: str,
    job: dict,
    segments: list[dict],
    on_stage: Callable[[str], None],
    research_topics: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """(title, sections) for a non-"document" transformation."""
    if transformation == "notes":
        sections, title_headings = compose_notes(segments, job.get("source_url"), on_stage)
    elif transformation == "study_guide":
        sections, title_headings = compose_study_guide(segments)
    elif transformation == "research":
        sections, title_headings = compose_research(segments, on_stage, research_topics)
    else:
        raise PipelineError(f"Unknown transformation {transformation!r}")
    # The section headings of a study guide ("Summary", "Key concepts") say
    # nothing about the video, so titles are generated from the topics instead.
    base = compose.generate_title([{"heading": h} for h in title_headings[:12]]) if title_headings else "Video"
    return f"{TITLE_PREFIX[transformation]}: {base}", sections
