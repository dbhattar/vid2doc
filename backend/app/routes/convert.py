import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import billing, jobs
from ..config import settings
from ..deps import get_current_user
from ..media import save_upload, title_from_filename

router = APIRouter()


@router.post("/api/convert_to_doc", status_code=202)
async def convert_to_doc(video: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    ext = Path(video.filename or "").suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Allowed: {sorted(settings.ALLOWED_EXTENSIONS)}",
        )

    job_id = str(uuid.uuid4())
    upload_dir = settings.UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"source{ext}"

    duration, size_bytes = await save_upload(
        video, upload_dir, dest_path, settings.MAX_UPLOAD_BYTES, settings.MAX_DURATION_SECONDS, kind="video"
    )

    # Pay-as-you-go: $1/video-hour, charged up front. No plans/tiers -- the
    # charge itself decides whether the upload is accepted, so it happens
    # before the job row exists (see models.py's note on related_job_id).
    try:
        billed_cents = billing.charge_for_job(current_user["id"], job_id, duration)
    except billing.InsufficientBalanceError as e:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient balance: this video costs ${e.required_cents / 100:.2f}, "
                f"you have ${e.balance_cents / 100:.2f}. Add funds at /settings/billing."
            ),
        )

    jobs.create_job(
        job_id,
        str(dest_path),
        user_id=current_user["id"],
        duration_seconds=duration,
        size_bytes=size_bytes,
        billed_cents=billed_cents,
        title=title_from_filename(video.filename or "", fallback="Untitled video"),
        job_type="video",
    )
    return {"job_id": job_id, "status": "queued"}
