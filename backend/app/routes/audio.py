import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import billing, jobs
from ..config import settings
from ..deps import get_current_user
from ..media import save_upload, title_from_filename

router = APIRouter()


@router.post("/api/transcribe_audio", status_code=202)
async def transcribe_audio(audio: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Audio-only counterpart to /api/convert_to_doc: produces a verbatim,
    speaker-tagged transcript -- no frame capture, no composed document (see
    pipeline.py's is_audio_job branch). Priced lower than a video job since
    it skips the vision-classification and compose LLM calls entirely."""
    ext = Path(audio.filename or "").suffix.lower()
    if ext not in settings.AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Allowed: {sorted(settings.AUDIO_EXTENSIONS)}",
        )

    job_id = str(uuid.uuid4())
    upload_dir = settings.UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"source{ext}"

    duration = await save_upload(
        audio, upload_dir, dest_path, settings.MAX_UPLOAD_BYTES, settings.MAX_DURATION_SECONDS, kind="audio"
    )

    try:
        billed_cents = billing.charge_for_job(current_user["id"], job_id, duration, job_type="audio")
    except billing.InsufficientBalanceError as e:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient balance: this audio costs ${e.required_cents / 100:.2f}, "
                f"you have ${e.balance_cents / 100:.2f}. Add funds at /settings/billing."
            ),
        )

    jobs.create_job(
        job_id,
        str(dest_path),
        user_id=current_user["id"],
        duration_seconds=duration,
        billed_cents=billed_cents,
        title=title_from_filename(audio.filename or "", fallback="Untitled audio"),
        job_type="audio",
    )
    return {"job_id": job_id, "status": "queued"}
