"""Business logic for chat-with-document (see routes/chat.py). A user
permanently enables chat on a completed job_type in ("video", "audio") job
for a flat one-time fee; this archives the document + transcript + original
source media to a private S3 prefix (mirrors app/public_jobs.py's archive
step, reusing its upload helper directly), then answers questions grounded
in that archived document, citing back a timestamp from the transcript
when the answer corresponds to a specific moment.

Unlike the public showcase archive, this one is never publicly listed or
readable -- "chat/{job_id}/" has no bucket-policy grant (only "public/*"
does, see deploy/aws/bucket-policy.json), and media playback goes through a
short-lived presigned URL (generate_media_url), not a public document_url.
"""

import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .db import get_session
from .models import ChatMessage
from .public_jobs import upload_job_archive
from .s3_client import get_client as get_s3_client


class ChatUnavailableError(Exception):
    """Raised when no LLM provider is configured -- distinct from
    PipelineError since this happens in a synchronous request handler
    (routes/chat.py), not the worker."""


SYSTEM_PROMPT_INSTRUCTIONS = """You are answering a user's question about a document generated from their own video or audio recording. You are given the full generated document and the original transcript (with per-segment timestamps in seconds).

Answer using ONLY information in the document below -- never invent facts it doesn't support. If your answer corresponds to specific moments in the recording, add up to 3 entries to citations, each a clip the user can play: start_seconds is the start_ts of the first transcript segment that supports your answer and end_seconds is the end_ts of the last contiguous supporting segment. Keep each clip under about 60 seconds and use only times that appear in the transcript. If no specific moment applies, or the document doesn't address the question, return an empty citations array and say so plainly in your answer -- never fabricate a citation."""

MAX_CITATIONS = 3
MAX_CLIP_SECONDS = 120

CITATIONS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "start_seconds": {"type": "number"},
            "end_seconds": {"type": "number"},
        },
        "required": ["start_seconds", "end_seconds"],
        "additionalProperties": False,
    },
}

ANSWER_TOOL = {
    "name": "submit_answer",
    "description": "Submit the answer to the user's question about this document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "citations": CITATIONS_SCHEMA,
        },
        "required": ["answer", "citations"],
    },
}

ANSWER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": CITATIONS_SCHEMA,
    },
    "required": ["answer", "citations"],
    "additionalProperties": False,
}


def archive_prefix_for(job_id: str) -> str:
    return f"chat/{job_id}/"


def _format_transcript(segments: list[dict]) -> str:
    if not segments:
        return "(no transcript available)"
    return "\n".join(
        f"[{s.get('start_ts', 0):.0f}s-{s.get('end_ts', s.get('start_ts', 0)):.0f}s] {s.get('speaker', '')}: {s.get('text', '')}"
        for s in segments
    )


def _system_prompt(document_text: str, segments: list[dict]) -> str:
    return (
        f"{SYSTEM_PROMPT_INSTRUCTIONS}\n\nDOCUMENT:\n{document_text}\n\n"
        f"TRANSCRIPT (for citing timestamps only):\n{_format_transcript(segments)}"
    )


def _answer_anthropic(client, system_prompt: str, messages: list[dict]) -> dict:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        system=system_prompt,
        tools=[ANSWER_TOOL],
        tool_choice={"type": "tool", "name": "submit_answer"},
        messages=messages,
    )
    for block in response.content:
        if block.type == "tool_use":
            return {"answer": block.input["answer"], "citations": block.input.get("citations") or []}
    return {"answer": "", "citations": []}


def _answer_openai(client, system_prompt: str, messages: list[dict]) -> dict:
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "system", "content": system_prompt}] + messages,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "submit_answer", "strict": True, "schema": ANSWER_JSON_SCHEMA},
        },
    )
    return json.loads(response.choices[0].message.content)


def validate_citations(raw: list, segments: list[dict]) -> list[dict]:
    """The model's clip times are untrusted -- drop anything malformed or
    outside the transcript, and clamp the rest so a hallucinated range can't
    seek past the end of the media or play for minutes."""
    if not segments:
        return []
    media_end = max(s.get("end_ts", s.get("start_ts", 0)) for s in segments)
    valid = []
    for c in raw or []:
        try:
            start, end = float(c["start_seconds"]), float(c["end_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            continue
        if start < 0 or start >= media_end or end <= start:
            continue
        end = min(end, media_end, start + MAX_CLIP_SECONDS)
        valid.append({"start_seconds": start, "end_seconds": end})
        if len(valid) == MAX_CITATIONS:
            break
    return valid


def _get_client_and_fn(provider: str):
    if provider == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ChatUnavailableError("OPENAI_API_KEY is not set")
        return openai.OpenAI(api_key=api_key), _answer_openai
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ChatUnavailableError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key), _answer_anthropic


def enable_chat(job: dict, doc_dir: Path) -> dict:
    """Archives document + transcript + source media to a private S3
    prefix -- reuses public_jobs.upload_job_archive as-is (already
    prefix-agnostic, already all-or-nothing with rollback on failure), just
    with a private prefix instead of showcase's public one. Caller
    (routes/chat.py) charges the flat fee BEFORE calling this, and refunds
    it if this raises."""
    prefix = archive_prefix_for(job["id"])
    video_filename = upload_job_archive(job["id"], doc_dir, Path(job["source_path"]), prefix)
    return {"chat_archive_prefix": prefix, "chat_video_key": video_filename}


MEDIA_URL_EXPIRES_SECONDS = 900


def generate_media_url(job: dict) -> str:
    """Short-lived presigned GET URL for the archived source media -- the
    frontend points a plain <video>/<audio> element's src directly at this,
    rather than proxy-streaming bytes through this API. S3 natively
    supports HTTP Range requests against a presigned URL, so seeking/
    scrubbing works with no extra backend code."""
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.PUBLIC_ARCHIVE_S3_BUCKET,
            "Key": f"{job['chat_archive_prefix']}{job['chat_video_key']}",
        },
        ExpiresIn=MEDIA_URL_EXPIRES_SECONDS,
    )


def _read_s3_text(prefix: str, filename: str) -> str:
    obj = get_s3_client().get_object(Bucket=settings.PUBLIC_ARCHIVE_S3_BUCKET, Key=f"{prefix}{filename}")
    return obj["Body"].read().decode("utf-8")


def answer_question(job: dict, history: list[dict], question: str) -> dict:
    """Reads document.md + transcript.json from S3 (not local disk -- by
    the time of any given chat message, local files may already be long
    gone per the normal 7-day retention sweep, which this feature is
    otherwise unaffected by since the archive already exists). `history` is
    prior chat_messages rows (role/content), oldest first."""
    prefix = job["chat_archive_prefix"]
    document_text = _read_s3_text(prefix, "document.md")
    try:
        transcript = json.loads(_read_s3_text(prefix, "transcript.json"))
    except Exception:
        transcript = {"segments": []}

    provider = settings.LLM_PROVIDER
    client, answer_fn = _get_client_and_fn(provider)

    system_prompt = _system_prompt(document_text, transcript.get("segments", []))
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": question})

    result = answer_fn(client, system_prompt, messages)
    result["citations"] = validate_citations(result.get("citations"), transcript.get("segments", []))
    return result


def _message_to_dict(m: ChatMessage) -> dict:
    citations = m.citations
    if citations is None and m.citation_seconds is not None:
        # Row from before clips existed -- a start with no known end.
        citations = [{"start_seconds": m.citation_seconds, "end_seconds": None}]
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "citation_seconds": m.citation_seconds,
        "citations": citations or [],
        "created_at": m.created_at,
    }


def list_chat_messages(job_id: str) -> list[dict]:
    session = get_session()
    try:
        rows = (
            session.query(ChatMessage)
            .filter(ChatMessage.job_id == job_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        return [_message_to_dict(m) for m in rows]
    finally:
        session.close()


def add_chat_message(job_id: str, role: str, content: str, citations: list[dict] | None = None) -> dict:
    """Explicit created_at (not server_default) so the dict returned here --
    used to build the API response immediately -- matches exactly what's
    persisted, no re-fetch needed."""
    session = get_session()
    try:
        message = ChatMessage(
            id=str(uuid.uuid4()),
            job_id=job_id,
            role=role,
            content=content,
            # citation_seconds stays populated (first clip's start) for
            # anything still reading the pre-clips column.
            citation_seconds=citations[0]["start_seconds"] if citations else None,
            citations=citations or None,
            created_at=datetime.now(timezone.utc),
        )
        session.add(message)
        session.commit()
        return _message_to_dict(message)
    finally:
        session.close()
