import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import billing, jobs
from ..config import settings
from ..deps import get_current_user
from ..media import save_upload

router = APIRouter()


@router.post("/api/live/finalize", status_code=202)
async def finalize_live_session(
    title: str = Form("Live Recording"),
    segments: str = Form(...),
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
    use -- see pipeline.py's _download_if_needed)."""
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
