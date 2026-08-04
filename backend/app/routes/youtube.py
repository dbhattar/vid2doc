import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import billing, jobs
from ..config import settings
from ..deps import get_current_user
from ..youtube import YoutubeDownloadError, fetch_metadata, is_youtube_url

router = APIRouter()


class YoutubeConvertRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.post("/api/convert_from_youtube", status_code=202)
def convert_from_youtube(body: YoutubeConvertRequest, current_user: dict = Depends(get_current_user)):
    """URL-based counterpart to /api/convert_to_doc. Only does a fast
    metadata lookup here (yt-dlp --dump-json, a couple seconds regardless of
    video length) to validate the URL and duration cap before creating the
    job -- the actual download is real I/O proportional to video length, so
    it's deferred to the worker (pipeline.py's _download_if_needed) instead
    of blocking this request the way frame extraction/transcription would if
    done here. Admins bypass MAX_DURATION_SECONDS entirely (see
    routes/convert.py's identical bypass) mainly so they can build longer
    showcase documents for demos -- re-checked at download time too, against
    admin status as of then, not now."""
    url = body.url.strip()
    if not is_youtube_url(url):
        raise HTTPException(status_code=400, detail="That doesn't look like a YouTube URL.")

    try:
        meta = fetch_metadata(url)
    except YoutubeDownloadError as e:
        raise HTTPException(status_code=400, detail=str(e))

    duration = meta.get("duration") or 0
    max_duration = None if current_user.get("is_admin") else settings.MAX_DURATION_SECONDS
    if max_duration is not None and duration > max_duration:
        raise HTTPException(
            status_code=400,
            detail=f"Video is {duration / 60:.0f} min -- exceeds the {max_duration // 60} min max.",
        )

    title = (meta.get("title") or "").strip()[:200] or "Untitled video"

    job_id = str(uuid.uuid4())
    try:
        billed_cents = billing.charge_for_job(current_user["id"], job_id, duration)
    except billing.InsufficientBalanceError as e:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient balance: this video costs ${e.required_cents / 100:.2f}, "
                f"you have ${e.balance_cents / 100:.2f}. Add funds at /settings/billing."
            ),
        )

    jobs.create_job(
        job_id,
        source_path=None,
        source_url=url,
        user_id=current_user["id"],
        duration_seconds=duration,
        billed_cents=billed_cents,
        title=title,
        job_type="video",
    )
    return {"job_id": job_id, "status": "queued"}
