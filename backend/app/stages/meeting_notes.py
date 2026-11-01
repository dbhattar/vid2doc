"""Summary, decisions and action items for a captured meeting -- the extra
sections a meeting's audio job gets on top of the verbatim transcript (see
pipeline.py's audio branch). Same `sections` shape as every other document
stage; one structured LLM call, via transform._call_json."""

from . import transform

SYSTEM_PROMPT = """You are writing the notes for a meeting from its speaker-tagged transcript.

Return:
- summary: 3-6 sentences on what the meeting covered and where it landed.
- decisions: each decision actually made, one short sentence each. Empty if none were made.
- action_items: each follow-up someone committed to or was assigned, with owner set to that person's name exactly as it appears in the transcript, or "Unassigned" if nobody was named.

Use only what the transcript says. Do not invent decisions or action items."""

SCHEMA = transform._object(
    {
        "summary": transform.STRING,
        "decisions": transform._array(transform.STRING),
        "action_items": transform._array(transform._object({"owner": transform.STRING, "item": transform.STRING})),
    }
)

# A very long meeting is truncated rather than windowed: notes only need the
# gist, and this is one cheap call.
MAX_TRANSCRIPT_CHARS = 120_000


def build_sections(segments: list[dict]) -> list[dict]:
    text = transform._transcript_text(segments)[:MAX_TRANSCRIPT_CHARS]
    data = transform._call_json(SYSTEM_PROMPT, f"TRANSCRIPT:\n{text}", "submit_meeting_notes", SCHEMA)

    sections = []
    if data.get("summary", "").strip():
        sections.append(transform._section("Summary", [data["summary"].strip()]))
    decisions = [d.strip() for d in data.get("decisions", []) if d.strip()]
    if decisions:
        sections.append(transform._section("Decisions", ["\n".join(f"- {d}" for d in decisions)]))
    actions = [a for a in data.get("action_items", []) if a.get("item", "").strip()]
    if actions:
        lines = [f"- **{a.get('owner', '').strip() or 'Unassigned'}**: {a['item'].strip()}" for a in actions]
        sections.append(transform._section("Action items", ["\n".join(lines)]))
    return sections
