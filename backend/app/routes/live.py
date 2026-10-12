import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import billing, jobs, live_research
from ..config import settings
from ..deps import get_current_user
from ..media import save_upload

router = APIRouter()

# Server-side caps on the live-research request body -- independent of
# whatever cadence/accumulation logic the frontend uses, so a modified or
# misbehaving client can't blow up the prompt size (and therefore cost)
# sent to OpenAI on every call.
MAX_RECENT_TEXT_CHARS = 4000
MAX_COVERED_TOPICS = 15
MAX_TOPIC_CHARS = 80


@router.post("/api/live/finalize", status_code=202)
async def finalize_live_session(
    title: str = Form("Live Recording"),
    segments: str = Form(...),
    research_notes: str = Form("[]"),
    research_references: str = Form("[]"),
    audio: UploadFile | None = File(None),
    current_user: dict = Depends(get_current_user),
):
    """Turns a client-side-diarized live-recording session into a normal
    audio job. Transcription + diarization already happened entirely in the
    browser (see plan/realtime-diarization-plan.md) -- this endpoint just
    persists the resulting segments and, optionally, the recorded audio
    itself, then queues a job_type="audio" job exactly like
    /api/transcribe_audio. pipeline.py's _transcribe_segments() finds
    precomputed_segments.json and skips straight past audio extraction and
    transcribe_diarize() (the same file YouTube-caption-derived transcripts
    use -- see pipeline.py's _download_if_needed).

    research_notes/research_references (both optional, from the opt-in live
    research panel -- see live_research.py) are pre-shaped and already
    deduped client-side; written here as document/research.md so it survives
    the pipeline run (doc_dir.mkdir(exist_ok=True) in pipeline.py never wipes
    pre-existing files) and ends up served by the ordinary
    GET /api/documents/{job_id}/research.md route once the job is done, same
    as document.docx/document.pdf (see routes/status.py's "advertised if
    present" pattern)."""
    try:
        parsed_segments = json.loads(segments)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="segments must be a JSON array")
    if not isinstance(parsed_segments, list) or not parsed_segments:
        raise HTTPException(status_code=400, detail="segments must be a non-empty JSON array")

    job_id = str(uuid.uuid4())
    upload_dir = settings.UPLOADS_DIR / job_id
    output_dir = settings.OUTPUT_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_path: str | None = None
    size_bytes: int | None = None
    duration = max(float(s.get("end_ts", 0)) for s in parsed_segments)

    if audio is not None:
        ext = Path(audio.filename or "").suffix.lower() or ".webm"
        dest_path = upload_dir / f"source{ext}"
        max_duration = None if current_user.get("is_admin") else settings.MAX_DURATION_SECONDS
        probed_duration, size_bytes = await save_upload(
            audio, upload_dir, dest_path, settings.MAX_UPLOAD_BYTES, max_duration, kind="audio"
        )
        source_path = str(dest_path)
        duration = probed_duration

    try:
        billed_cents = billing.charge_for_job(current_user["id"], job_id, duration, job_type="audio")
    except billing.InsufficientBalanceError as e:
        shutil.rmtree(upload_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient balance: this recording costs ${e.required_cents / 100:.2f}, "
                f"you have ${e.balance_cents / 100:.2f}. Add funds at /settings/billing."
            ),
        )

    (output_dir / "precomputed_segments.json").write_text(json.dumps(parsed_segments))

    try:
        notes = json.loads(research_notes)
        references = json.loads(research_references)
    except json.JSONDecodeError:
        notes, references = [], []
    if notes or references:
        doc_dir = output_dir / "document"
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "research.md").write_text(live_research.render_research_document(notes, references))

    jobs.create_job(
        job_id,
        source_path,
        user_id=current_user["id"],
        duration_seconds=duration,
        size_bytes=size_bytes,
        billed_cents=billed_cents,
        title=title[:200] or "Live Recording",
        job_type="audio",
    )
    return {"job_id": job_id, "status": "queued"}


class LiveResearchRequest(BaseModel):
    recent_text: str
    covered_topics: list[str] = []


@router.post("/api/live/research")
def get_live_research(body: LiveResearchRequest, current_user: dict = Depends(get_current_user)) -> dict:
    """Opt-in, best-effort: the frontend calls this periodically during a
    live session with whatever's been said since the last call, and gets
    back a short research note on the current topic (or null -- see
    live_research.get_research_note's own docstring for why that's a real,
    expected response, not an error case). Stateless -- no Job row, no
    persistence, nothing billed (see plan/live-research-panel-plan.md for
    why: free for now, with LIVE_RESEARCH_ENABLED as the kill switch and
    live_research.check_rate_limit as the only cost safety net)."""
    if not settings.LIVE_RESEARCH_ENABLED:
        raise HTTPException(status_code=503, detail="Live research is temporarily unavailable.")

    text = body.recent_text.strip()[:MAX_RECENT_TEXT_CHARS]
    if not text:
        raise HTTPException(status_code=400, detail="recent_text must not be empty")
    covered_topics = [t[:MAX_TOPIC_CHARS] for t in body.covered_topics[:MAX_COVERED_TOPICS]]

    try:
        live_research.check_rate_limit(current_user["id"])
    except live_research.LiveResearchRateLimitedError:
        raise HTTPException(status_code=429, detail="Too many live-research requests -- please slow down.")

    try:
        note = live_research.get_research_note(text, covered_topics)
    except live_research.LiveResearchUnavailableError:
        raise HTTPException(status_code=503, detail="Live research is temporarily unavailable -- no OpenAI API key configured")
    except Exception:
        raise HTTPException(status_code=502, detail="Could not fetch research right now -- please try again shortly")

    return {"note": note}
