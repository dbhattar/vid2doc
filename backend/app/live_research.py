"""Business logic for the live-transcription "research" side panel (see
routes/live.py's POST /api/live/research). As a live session runs, the
frontend periodically sends the recent transcript text here and gets back
a short, genuinely useful research note about whatever topic is currently
being discussed -- or null, if nothing new/researchable has come up since
the last call.

Unlike every other LLM integration in this codebase (stages/*.py,
chat_jobs.py), this is OpenAI-only, with no Anthropic fallback branch --
web search is specifically an OpenAI API capability here (the `web_search`
built-in tool on the Responses API), not something both providers equally
support via this codebase's existing LLM_PROVIDER switch.

Stateless by design: no session/job row, no persistence. The frontend owns
the accumulating transcript window and the rolling "already covered"
topics list entirely client-side (see plan/live-research-panel-plan.md) --
this module only ever processes exactly what one call sends it.
"""

import json
import os
import time

from .config import settings


class LiveResearchUnavailableError(Exception):
    """Raised when OPENAI_API_KEY is not set -- distinct from the batch
    pipeline's PipelineError since this happens in a synchronous request
    handler (routes/live.py), not a worker."""


class LiveResearchRateLimitedError(Exception):
    """Raised when one user has made too many research calls too quickly --
    the only real cost safety net for this feature today (see
    plan/live-research-panel-plan.md's explicit "free for now, but real
    OpenAI cost" framing). In-process only: resets on restart and doesn't
    coordinate across multiple backend replicas -- fine while usage is low,
    first thing to upgrade (e.g. to a DB-backed counter) if that changes."""


SYSTEM_PROMPT_INSTRUCTIONS = """You are watching a live transcript of a conversation or talk as it happens and surfacing brief, genuinely useful background research on whatever topic is currently being discussed -- the kind of thing a well-informed listener might want pulled up in a side panel.

Use web search to ground your answer in real, current information where it helps (e.g. facts, context, recent developments) rather than relying only on what you already know.

Only return a note if the recent transcript introduces something substantive and genuinely researchable that has NOT already been covered this session (see the list of already-covered topics below) -- if nothing new and researchable has come up, set "note" to null rather than forcing something generic or repeating an earlier topic. Keep the note itself concise: a sentence or two of real signal, not a summary of what was said."""

RESEARCH_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "note": {
            "type": ["object", "null"],
            "properties": {
                "topic": {"type": "string", "description": "Short label for the topic, e.g. 'Raft consensus algorithm'"},
                "body": {"type": "string", "description": "A sentence or two of genuinely useful background"},
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
                        "required": ["title", "url"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["topic", "body", "links"],
            "additionalProperties": False,
        },
    },
    "required": ["note"],
    "additionalProperties": False,
}

# Rolling per-user call log for the rate limit below -- see
# LiveResearchRateLimitedError's docstring for why this is deliberately
# simple (in-process, not DB-backed) rather than a design oversight.
_RATE_LIMIT_WINDOW_SECONDS = 600
_RATE_LIMIT_MAX_CALLS = 20
_call_log: dict[str, list[float]] = {}


def check_rate_limit(user_id: str) -> None:
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    recent = [t for t in _call_log.get(user_id, []) if t >= cutoff]
    if len(recent) >= _RATE_LIMIT_MAX_CALLS:
        _call_log[user_id] = recent
        raise LiveResearchRateLimitedError(
            f"More than {_RATE_LIMIT_MAX_CALLS} live-research calls in {_RATE_LIMIT_WINDOW_SECONDS}s"
        )
    recent.append(now)
    _call_log[user_id] = recent


def _user_prompt(recent_text: str, covered_topics: list[str]) -> str:
    covered = ", ".join(covered_topics) if covered_topics else "(none yet)"
    return f"Topics already covered this session (don't repeat these): {covered}\n\nRecent transcript:\n{recent_text}"


def get_research_note(recent_text: str, covered_topics: list[str]) -> dict | None:
    """One OpenAI Responses API call with the built-in `web_search` tool
    plus strict structured output, returning the shaped note or None.

    NOTE ON API SHAPE: verified against OpenAI's current docs at the time
    this was written (client.responses.create(..., tools=[{"type":
    "web_search"}], text={"format": {"type": "json_schema", ...}})) rather
    than assumed -- but OpenAI's API surface for this moves fast, so if
    this starts failing, re-check https://platform.openai.com/docs/guides/tools-web-search
    and https://platform.openai.com/docs/guides/structured-outputs before
    assuming the rest of this module is wrong. `web_search` (not the older
    `web_search_preview`) is the current, non-legacy tool type.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LiveResearchUnavailableError("OPENAI_API_KEY is not set")

    import openai

    client = openai.OpenAI(api_key=api_key)
    response = client.responses.create(
        model=settings.LIVE_RESEARCH_OPENAI_MODEL,
        tools=[{"type": "web_search"}],
        instructions=SYSTEM_PROMPT_INSTRUCTIONS,
        input=_user_prompt(recent_text, covered_topics),
        text={
            "format": {
                "type": "json_schema",
                "name": "submit_research_note",
                "strict": True,
                "schema": RESEARCH_JSON_SCHEMA,
            }
        },
    )
    result = json.loads(response.output_text)
    return result.get("note")


def render_research_document(notes: list[dict], references: list[dict]) -> str:
    """Renders one live session's accumulated research notes + already-deduped
    references (both shaped client-side -- see frontend's handleStop, which
    computes the dedup once and sends the result here rather than this module
    re-deriving it) into a plain markdown document. Written by routes/live.py
    to this job's document/research.md, which the existing generic
    GET /api/documents/{job_id}/{file_path} route (routes/documents.py)
    already serves -- no new serving route needed, same as document.docx/
    document.pdf being "advertised if present" in routes/status.py."""
    lines = ["# Live Research", ""]
    for note in notes:
        topic = (note.get("topic") or "").strip()
        body = (note.get("body") or "").strip()
        if not topic and not body:
            continue
        lines.append(f"## {topic}" if topic else "## Note")
        lines.append("")
        lines.append(body)
        lines.append("")
    if references:
        lines.append("## References")
        lines.append("")
        for ref in references:
            url = (ref.get("url") or "").strip()
            if not url:
                continue
            title = (ref.get("title") or "").strip() or url
            lines.append(f"- [{title}]({url})")
        lines.append("")
    return "\n".join(lines)
