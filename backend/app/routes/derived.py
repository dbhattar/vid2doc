"""The initial set a finished video job gives (document, transcript, images)
plus the "make more documents from it" actions, which an audio transcript has
too. See app/derived.py."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import archive_access, derived, jobs
from ..deps import get_current_user
from .status import build_job_response

router = APIRouter()

_IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class DeriveRequest(BaseModel):
    transformation: str
    review_topics: bool = False


def _parent(job_id: str, current_user: dict) -> dict:
    try:
        return derived.check_parent(jobs.get_job(job_id), current_user["id"])
    except derived.DerivedError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/api/jobs/{job_id}/derive", status_code=202)
def derive_document(job_id: str, body: DeriveRequest, request: Request, current_user: dict = Depends(get_current_user)):
    parent = _parent(job_id, current_user)
    try:
        child = derived.create(parent, current_user["id"], body.transformation, body.review_topics)
    except derived.DerivedError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return build_job_response(child, request)


@router.get("/api/jobs/{job_id}/derived")
def list_derived(job_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """What can be made from this video, what it would cost, and what has been
    made so far."""
    parent = _parent(job_id, current_user)
    can_create, reason = derived.availability(parent)
    return {
        "can_create": can_create,
        "reason": reason,
        "options": [
            {"transformation": t, "cost_cents": derived.cost_cents(t, parent["duration_seconds"])} for t in derived.DERIVABLE
        ],
        "documents": [build_job_response(c, request) for c in jobs.list_child_jobs(job_id)],
    }


@router.get("/api/jobs/{job_id}/images")
def list_images(job_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """The images (slides, diagrams, tables) captured from the video."""
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"] or job["status"] != "done" or job["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail="Job not found")
    images_dir = archive_access.ensure_local(job) / "images"
    base = f"{str(request.base_url).rstrip('/')}/api/documents/{job_id}/images"
    names = (
        sorted(p.name for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_TYPES)
        if images_dir.is_dir()
        else []
    )
    return {"images": [{"name": n, "url": f"{base}/{n}"} for n in names]}
