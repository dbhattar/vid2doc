"""Serves the finished video and its thumbnail for a job_type == "video_gen"
job. Mirrors documents.py's ownership-guard pattern for "done" jobs.
"""

import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from .. import job_storage, jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def _owned_done_video(job_id: str, current_user: dict) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"] or job["job_type"] != "video_gen" or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Video not found")
    if job["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail="This video is no longer available")
    if job_storage.is_stored(job):
        if not job_storage.has_file(job, "video/final.mp4"):
            raise HTTPException(status_code=404, detail="Video not found")
        return job
    if not job["document_path"] or not Path(job["document_path"]).is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return job


@router.get("/api/videos/{job_id}/output.mp4")
def get_video_output(job_id: str, current_user: dict = Depends(get_current_user)):
    job = _owned_done_video(job_id, current_user)
    if job_storage.is_stored(job):
        # Short-lived signed URL so the browser can Range-seek straight from S3.
        return RedirectResponse(job_storage.presigned_url(job, "video/final.mp4"), status_code=302)
    return FileResponse(job["document_path"], media_type="video/mp4")


@router.get("/api/videos/{job_id}/thumbnail.jpg")
def get_video_thumbnail(job_id: str, current_user: dict = Depends(get_current_user)):
    job = _owned_done_video(job_id, current_user)
    if job_storage.is_stored(job):
        if not job_storage.has_file(job, "video/thumbnail.jpg"):
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        chunks, size, content_type = job_storage.open_stream(job, "video/thumbnail.jpg")
        return StreamingResponse(chunks, media_type=content_type, headers={"Content-Length": str(size)})
    thumbnail_path = settings.OUTPUT_DIR / job_id / "video" / "thumbnail.jpg"
    if not thumbnail_path.is_file():
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", job["document_path"], "-ss", "0", "-vframes", "1", str(thumbnail_path)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail="Could not generate thumbnail") from e
    return FileResponse(thumbnail_path)
