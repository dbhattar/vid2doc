import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import billing, jobs
from ..config import settings
from ..deps import get_current_user
from ..media import save_upload, title_from_filename

router = APIRouter()


@router.post("/api/generate_video", status_code=202)
async def generate_video(audio: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Audio -> generated video (job_type == "video_gen"): transcribes the
    uploaded narration, segments it into scenes, matches stock visuals per
    scene, then pauses for scene review (see routes/scene_review.py) before
    the actual (CPU-heavy) rendering runs. 16:9 only in v1 -- see config.py's
    aspect_ratio note."""
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

    # Admins bypass the duration cap entirely -- see routes/convert.py.
    max_duration = None if current_user.get("is_admin") else settings.VIDEO_GEN_MAX_DURATION_SECONDS
    duration, size_bytes = await save_upload(
        audio, upload_dir, dest_path, settings.MAX_UPLOAD_BYTES, max_duration, kind="audio"
    )

    try:
        billed_cents = billing.charge_for_job(current_user["id"], job_id, duration, job_type="video_gen")
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
        title=title_from_filename(audio.filename or "", fallback="Untitled video"),
        job_type="video_gen",
    )
    return {"job_id": job_id, "status": "queued"}
