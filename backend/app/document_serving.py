"""Serving a job's document files, shared by the owner routes
(routes/documents.py) and the public share routes (routes/share.py). A job
stored in private S3 (see job_storage.py) is streamed from there; a legacy
job is read from local disk."""

import io
import posixpath
import zipfile

from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from . import archive_access, job_storage


def _local_doc_dir(job: dict):
    """The local doc dir of a job that isn't in private storage -- rebuilt from
    its showcase/chat archive first if retention has swept it."""
    return archive_access.ensure_local(job)


def file_response(job: dict, file_path: str):
    if job_storage.is_stored(job):
        rel = posixpath.normpath(f"document/{file_path}")
        # normpath resolves "..", so confine the result to document/ -- the
        # source media and video/ files are stored beside it and have their
        # own routes.
        if not rel.startswith("document/") or not job_storage.has_file(job, rel):
            raise HTTPException(status_code=404, detail="File not found")
        chunks, size, content_type = job_storage.open_stream(job, rel)
        return StreamingResponse(chunks, media_type=content_type, headers={"Content-Length": str(size)})
    doc_dir = _local_doc_dir(job)
    full_path = (doc_dir / file_path).resolve()
    if not full_path.is_relative_to(doc_dir):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(full_path)


def bundle_response(job: dict, filename: str):
    """document.md plus images/ as a zip, built in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if job_storage.is_stored(job):
            if not job_storage.has_file(job, "document/document.md"):
                raise HTTPException(status_code=404, detail="Document not found")
            for rel in job["storage_files"]:
                if rel == "document/document.md" or rel.startswith("document/images/"):
                    zf.writestr(rel[len("document/"):], job_storage.read_bytes(job, rel))
        else:
            doc_dir = _local_doc_dir(job)
            md_path = doc_dir / "document.md"
            if not md_path.is_file():
                raise HTTPException(status_code=404, detail="Document not found")
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
