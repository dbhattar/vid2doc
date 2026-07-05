from fastapi import APIRouter, Depends, HTTPException, Request

from .. import jobs
from ..auth import verify_api_key
from ..config import settings

router = APIRouter()


@router.get("/api/get_status", dependencies=[Depends(verify_api_key)])
def get_status(job_id: str, request: Request):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": job["id"],
        "status": job["status"],
        "progress_stage": job["progress_stage"],
    }
    if job["status"] == "done":
        base = f"{str(request.base_url).rstrip('/')}/api/documents/{job['id']}"
        doc_dir = settings.OUTPUT_DIR / job["id"] / "document"
        response["document_url"] = f"{base}/document.md"
        # docx/pdf are best-effort exports -- only advertised if they actually rendered.
        if (doc_dir / "document.docx").exists():
            response["document_docx_url"] = f"{base}/document.docx"
        if (doc_dir / "document.pdf").exists():
            response["document_pdf_url"] = f"{base}/document.pdf"
    if job["status"] == "failed":
        response["error"] = job["error_message"]
    return response
