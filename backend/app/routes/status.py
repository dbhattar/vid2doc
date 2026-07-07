from fastapi import APIRouter, Depends, HTTPException, Request

from .. import jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def build_job_response(job: dict, request: Request) -> dict:
    """Shared by GET /api/get_status and GET /api/jobs -- a job list item has
    exactly the same shape as a single-job status response."""
    response = {
        "job_id": job["id"],
        "status": job["status"],
        "progress_stage": job["progress_stage"],
        "created_at": job["created_at"],
        "duration_seconds": job["duration_seconds"],
    }
    if job["status"] == "done" and job["deleted_at"] is not None:
        # Retention swept the files (see retention.py) -- still "done" in
        # the sense that conversion succeeded, but nothing left to serve.
        response["retention_expired"] = True
    elif job["status"] == "done":
        base = f"{str(request.base_url).rstrip('/')}/api/documents/{job['id']}"
        doc_dir = settings.OUTPUT_DIR / job["id"] / "document"
        response["document_url"] = f"{base}/document.md"
        response["document_bundle_url"] = f"{base}/bundle.zip"
        # docx/pdf are best-effort exports -- only advertised if they actually rendered.
        if (doc_dir / "document.docx").exists():
            response["document_docx_url"] = f"{base}/document.docx"
        if (doc_dir / "document.pdf").exists():
            response["document_pdf_url"] = f"{base}/document.pdf"
    if job["status"] == "failed":
        response["error"] = job["error_message"]
    return response


@router.get("/api/get_status")
def get_status(job_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_job_response(job, request)
