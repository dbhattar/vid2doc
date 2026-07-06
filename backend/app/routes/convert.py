import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import billing, jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def _probe_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


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

    size = 0
    try:
        with open(dest_path, "wb") as f:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > settings.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Video exceeds max upload size of {settings.MAX_UPLOAD_BYTES} bytes",
                    )
                f.write(chunk)
    except HTTPException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    if size == 0:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        duration = _probe_duration_seconds(dest_path)
    except (ValueError, OSError):
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Could not read video file -- is it a valid video?")

    if duration > settings.MAX_DURATION_SECONDS:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail=f"Video duration {duration:.0f}s exceeds max of {settings.MAX_DURATION_SECONDS}s",
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
        job_id, str(dest_path), user_id=current_user["id"], duration_seconds=duration, billed_cents=billed_cents
    )
    return {"job_id": job_id, "status": "queued"}
