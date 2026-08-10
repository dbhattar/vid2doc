"""Public, unauthenticated read access to one job's rendered documents via
an unguessable share link -- opt-in per job, toggled owner-only. Modeled
directly on routes/trial.py's tokenless document endpoints, keyed by
share_token instead of "no owner at all". Never exposes user_id, client_ip,
billed_cents, or error_message -- only title/job_type/duration_seconds/
created_at and derived document URLs.
"""

import io
import secrets
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .. import jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def _owned_job(job_id: str, current_user: dict) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/api/jobs/{job_id}/share")
def enable_share(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    """Idempotent: re-calling while already shared returns the same link
    rather than rotating it out from under anyone it's already been sent to.
    Only a completed, un-expired job can be shared."""
    job = _owned_job(job_id, current_user)
    if job["status"] != "done" or job["deleted_at"] is not None:
        raise HTTPException(status_code=400, detail="Only a completed, un-expired job can be shared")
    token = job["share_token"] or secrets.token_urlsafe(24)
    if token != job["share_token"]:
        jobs.update_job(job_id, share_token=token)
    return {"share_token": token, "share_url": f"{settings.FRONTEND_URL}/share/{token}"}


@router.delete("/api/jobs/{job_id}/share", status_code=204)
def disable_share(job_id: str, current_user: dict = Depends(get_current_user)) -> None:
    _owned_job(job_id, current_user)
    jobs.update_job(job_id, share_token=None)


def _shared_job_and_doc_dir(token: str) -> tuple[dict, Path]:
    job = jobs.get_job_by_share_token(token)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Shared document not found")
    if job["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail="This document was deleted after 7 days per the retention policy")
    return job, (settings.OUTPUT_DIR / job["id"] / "document").resolve()


def _build_public_response(job: dict, request: Request) -> dict:
    base = f"{str(request.base_url).rstrip('/')}/api/share/{job['share_token']}/documents"
    doc_dir = settings.OUTPUT_DIR / job["id"] / "document"
    response = {
        "title": job["title"],
        "job_type": job["job_type"],
        "duration_seconds": job["duration_seconds"],
        "created_at": job["created_at"],
        "document_url": f"{base}/document.md",
        "document_bundle_url": f"{base}/bundle.zip",
    }
    if (doc_dir / "document.docx").exists():
        response["document_docx_url"] = f"{base}/document.docx"
    if (doc_dir / "document.pdf").exists():
        response["document_pdf_url"] = f"{base}/document.pdf"
    if (doc_dir / "transcript.json").exists():
        response["document_transcript_json_url"] = f"{base}/transcript.json"
    return response


@router.get("/api/share/{token}")
def get_shared_job(token: str, request: Request) -> dict:
    job, _ = _shared_job_and_doc_dir(token)
    return _build_public_response(job, request)


# Registered before the {file_path:path} catch-all below, same reasoning as
# routes/documents.py's / routes/trial.py's equivalent pair -- Starlette
# matches route registration order, so this specific path must come first.
@router.get("/api/share/{token}/documents/bundle.zip")
def get_shared_bundle(token: str):
    _, doc_dir = _shared_job_and_doc_dir(token)
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
    # Generic filename, not job_id -- a public download shouldn't leak an internal id.
    return StreamingResponse(
        buffer, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="document.zip"'}
    )


@router.get("/api/share/{token}/documents/{file_path:path}")
def get_shared_document_file(token: str, file_path: str):
    _, doc_dir = _shared_job_and_doc_dir(token)
    full_path = (doc_dir / file_path).resolve()
    if not full_path.is_relative_to(doc_dir):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(full_path)
