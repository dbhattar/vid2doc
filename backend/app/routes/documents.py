import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from .. import jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def _owned_done_doc_dir(job_id: str, current_user: dict):
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"] or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Document not found")
    if job["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail="This document was deleted after 7 days per the retention policy")
    return (settings.OUTPUT_DIR / job_id / "document").resolve()


# Registered before the {file_path:path} catch-all below -- Starlette matches
# routes in registration order, so this specific path must come first or the
# catch-all would swallow "bundle.zip" as a literal file_path lookup.
@router.get("/api/documents/{job_id}/bundle.zip")
def get_document_bundle(job_id: str, current_user: dict = Depends(get_current_user)):
    doc_dir = _owned_done_doc_dir(job_id, current_user)
    md_path = doc_dir / "document.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(md_path, arcname="document.md")
        images_dir = doc_dir / "images"
        if images_dir.is_dir():
            for image_path in sorted(images_dir.iterdir()):
                if image_path.is_file():
                    zf.write(image_path, arcname=f"images/{image_path.name}")
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.zip"'},
    )


@router.get("/api/documents/{job_id}/{file_path:path}")
def get_document_file(job_id: str, file_path: str, current_user: dict = Depends(get_current_user)):
    doc_dir = _owned_done_doc_dir(job_id, current_user)
    full_path = (doc_dir / file_path).resolve()
    if not full_path.is_relative_to(doc_dir):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(full_path)
