"""Public, unauthenticated read access to one job's rendered documents via
an unguessable share link -- opt-in per job, toggled owner-only, keyed by
share_token. Never exposes user_id, client_ip, billed_cents, or
error_message -- only title/job_type/duration_seconds/created_at and
derived document URLs.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import archive_access, document_serving, job_storage, jobs
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
    if job["status"] != "done" or archive_access.is_expired(job):
        raise HTTPException(status_code=400, detail="Only a completed, un-expired job can be shared")
    token = job["share_token"] or secrets.token_urlsafe(24)
    if token != job["share_token"]:
        jobs.update_job(job_id, share_token=token)
    return {"share_token": token, "share_url": f"{settings.FRONTEND_URL}/share/{token}"}


@router.delete("/api/jobs/{job_id}/share", status_code=204)
def disable_share(job_id: str, current_user: dict = Depends(get_current_user)) -> None:
    _owned_job(job_id, current_user)
    jobs.update_job(job_id, share_token=None)


def _shared_job(token: str) -> dict:
    job = jobs.get_job_by_share_token(token)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Shared document not found")
    if archive_access.is_expired(job):
        raise HTTPException(status_code=404, detail="This document is no longer available")
    return job


def _build_public_response(job: dict, request: Request) -> dict:
    base = f"{str(request.base_url).rstrip('/')}/api/share/{job['share_token']}/documents"
    response = {
        "title": job["title"],
        "job_type": job["job_type"],
        "duration_seconds": job["duration_seconds"],
        "created_at": job["created_at"],
        "document_url": f"{base}/document.md",
        "document_bundle_url": f"{base}/bundle.zip",
    }
    if job_storage.has_doc_file(job, "document.docx"):
        response["document_docx_url"] = f"{base}/document.docx"
    if job_storage.has_doc_file(job, "document.pdf"):
        response["document_pdf_url"] = f"{base}/document.pdf"
    if job_storage.has_doc_file(job, "transcript.json"):
        response["document_transcript_json_url"] = f"{base}/transcript.json"
    return response


@router.get("/api/share/{token}")
def get_shared_job(token: str, request: Request) -> dict:
    job = _shared_job(token)
    return _build_public_response(job, request)


# Registered before the {file_path:path} catch-all below, same reasoning as
# routes/documents.py's equivalent pair -- Starlette matches route
# registration order, so this specific path must come first.
@router.get("/api/share/{token}/documents/bundle.zip")
def get_shared_bundle(token: str):
    # Generic filename, not job_id -- a public download shouldn't leak an internal id.
    return document_serving.bundle_response(_shared_job(token), "document.zip")


@router.get("/api/share/{token}/documents/{file_path:path}")
def get_shared_document_file(token: str, file_path: str):
    return document_serving.file_response(_shared_job(token), file_path)
