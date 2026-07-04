from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import jobs
from ..auth import verify_api_key
from ..config import settings

router = APIRouter()


@router.get("/api/documents/{job_id}/{file_path:path}", dependencies=[Depends(verify_api_key)])
def get_document_file(job_id: str, file_path: str):
    job = jobs.get_job(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Document not found")

    doc_dir = (settings.OUTPUT_DIR / job_id / "document").resolve()
    full_path = (doc_dir / file_path).resolve()
    if not full_path.is_relative_to(doc_dir):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(full_path)
