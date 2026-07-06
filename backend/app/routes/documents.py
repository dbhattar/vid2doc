from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


@router.get("/api/documents/{job_id}/{file_path:path}")
def get_document_file(job_id: str, file_path: str, current_user: dict = Depends(get_current_user)):
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"] or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Document not found")

    doc_dir = (settings.OUTPUT_DIR / job_id / "document").resolve()
    full_path = (doc_dir / file_path).resolve()
    if not full_path.is_relative_to(doc_dir):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(full_path)
