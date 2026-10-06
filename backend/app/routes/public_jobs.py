"""Owner-facing opt-in ("make this job public for a partial refund") and the
public, unauthenticated showcase read endpoints -- mirrors routes/share.py's
dual ownership of "owner action" + "public read" for one feature. See
app/public_jobs.py for the business logic (S3 archive, refund, moderation
state machine) and its module docstring for the full design rationale.
Never exposes user_id, billed_cents, public_refund_cents, client_ip,
error_message, or any internal storage detail (the raw archive prefix) --
only title/duration_seconds/featured_since and derived document URLs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import jobs, public_jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


@router.post("/api/jobs/{job_id}/public-consent")
def submit_public_consent(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["job_type"] != "video":
        raise HTTPException(status_code=400, detail="Only completed video-to-document jobs can be made public")
    if job["status"] != "done" or job["deleted_at"] is not None:
        raise HTTPException(status_code=400, detail="Only a completed, un-expired job can be made public")
    if job["public_status"] is not None:
        raise HTTPException(status_code=400, detail=f"Already {job['public_status']} for public showcase")

    doc_dir = (settings.OUTPUT_DIR / job_id / "document").resolve()
    try:
        return public_jobs.submit_public_consent(job, doc_dir)
    except public_jobs.PublicArchiveUploadError:
        raise HTTPException(status_code=502, detail="Could not archive this job for public review -- please try again")


def _build_showcase_response(job: dict, full: bool = False) -> dict:
    """`full=True` (single-item detail only, never the list endpoint) also
    checks for optional archived files via S3 HEAD calls -- too many calls
    to do per row on a paginated list."""
    prefix = job["public_archive_prefix"]
    base = f"{settings.PUBLIC_ARCHIVE_BASE_URL}/{prefix}"
    response = {
        "id": job["id"],
        "title": job["title"],
        "duration_seconds": job["duration_seconds"],
        "featured_since": job["public_reviewed_at"],
        "document_url": f"{base}document.md",
    }
    if full:
        if public_jobs.archive_file_exists(prefix, "document.docx"):
            response["document_docx_url"] = f"{base}document.docx"
        if public_jobs.archive_file_exists(prefix, "document.pdf"):
            response["document_pdf_url"] = f"{base}document.pdf"
        if public_jobs.archive_file_exists(prefix, "transcript.json"):
            response["document_transcript_json_url"] = f"{base}transcript.json"
    return response


@router.get("/api/public/showcase")
def list_showcase(limit: int = Query(default=20, ge=1, le=50), offset: int = Query(default=0, ge=0)) -> dict:
    approved = jobs.list_jobs_by_public_status("approved", limit=limit, offset=offset)
    return {
        "jobs": [_build_showcase_response(j) for j in approved],
        "total": jobs.count_jobs_by_public_status("approved"),
    }


@router.get("/api/public/showcase/{job_id}")
def get_showcase_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["public_status"] != "approved":
        raise HTTPException(status_code=404, detail="Not found")
    return _build_showcase_response(job, full=True)
