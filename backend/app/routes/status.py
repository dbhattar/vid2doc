from fastapi import APIRouter, Depends, HTTPException, Request

from .. import jobs
from ..auth import verify_api_key

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
        response["document_url"] = f"{str(request.base_url).rstrip('/')}/api/documents/{job['id']}/document.md"
    if job["status"] == "failed":
        response["error"] = job["error_message"]
    return response
