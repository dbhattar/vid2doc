from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import activity, billing, feedback, jobs, public_jobs, users
from ..deps import get_current_admin_user
from .public_jobs import _build_showcase_response

router = APIRouter()


@router.get("/api/admin/stats")
def get_admin_stats(current_user: dict = Depends(get_current_admin_user)):
    all_users = users.list_users_with_stats(limit=100_000)
    top_spenders = sorted(all_users, key=lambda u: u["spent_cents"], reverse=True)[:5]
    job_counts = jobs.count_jobs_by_type()

    return {
        "user_count": users.count_users(),
        "total_revenue_cents": billing.total_revenue_cents(),
        "total_spent_cents": sum(u["spent_cents"] for u in all_users),
        "job_counts": {
            "video": job_counts.get("video", 0),
            "audio": job_counts.get("audio", 0),
            "total": sum(job_counts.values()),
        },
        "total_source_size_bytes": jobs.total_source_size_bytes(),
        "top_spenders": [
            {
                "id": u["id"],
                "email": u["email"],
                "display_name": u["display_name"],
                "spent_cents": u["spent_cents"],
            }
            for u in top_spenders
        ],
    }


@router.get("/api/admin/users")
def list_admin_users(current_user: dict = Depends(get_current_admin_user)):
    return {"users": users.list_users_with_stats(limit=500)}


@router.get("/api/admin/feedback")
def list_admin_feedback(current_user: dict = Depends(get_current_admin_user)):
    return {"feedback": feedback.list_feedback_with_users(limit=500)}


@router.get("/api/admin/activity")
def list_admin_activity(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_admin_user),
):
    events, total = activity.list_recent_activity(limit=limit, offset=offset)
    return {"activity": events, "total": total}


@router.get("/api/admin/jobs")
def list_admin_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    job_type: str | None = Query(default=None, description="Filter to one job type, e.g. job_type=video"),
    current_user: dict = Depends(get_current_admin_user),
):
    return {
        "jobs": jobs.list_all_jobs(limit=limit, offset=offset, job_type=job_type),
        "total": jobs.count_all_jobs(job_type=job_type),
    }


@router.get("/api/admin/users/{user_id}")
def get_admin_user(user_id: str, current_user: dict = Depends(get_current_admin_user)):
    user = users.get_user_with_stats(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/api/admin/users/{user_id}/activity")
def list_admin_user_activity(
    user_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_admin_user),
):
    if not users.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    events, total = activity.list_activity_for_user(user_id, limit=limit, offset=offset)
    return {"activity": events, "total": total}


class SetAdminRequest(BaseModel):
    is_admin: bool


@router.post("/api/admin/users/{user_id}/admin")
def set_user_admin_status(
    user_id: str, body: SetAdminRequest, current_user: dict = Depends(get_current_admin_user)
):
    updated = users.set_admin_status(user_id, body.is_admin)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.get("/api/admin/public-jobs")
def list_admin_public_jobs(
    status: str = Query(default="pending", pattern="^(pending|approved|rejected)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_admin_user),
):
    return {
        "jobs": jobs.list_jobs_by_public_status(status, limit=limit, offset=offset),
        "total": jobs.count_jobs_by_public_status(status),
    }


@router.get("/api/admin/public-jobs/{job_id}")
def get_admin_public_job(job_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Full job dict (admin-only, unlike the whitelisted public showcase
    response) plus the archived document's URLs -- reuses
    routes/public_jobs.py's _build_showcase_response for those since the
    archive already exists at opt-in time (see app/public_jobs.py's module
    docstring), regardless of whether this job has been reviewed yet."""
    job = jobs.get_job(job_id)
    if not job or job["public_status"] is None:
        raise HTTPException(status_code=404, detail="Job not found")
    owner = users.get_user_by_id(job["user_id"]) if job["user_id"] else None
    return {
        **job,
        "email": owner["email"] if owner else None,
        "display_name": owner["display_name"] if owner else None,
        **_build_showcase_response(job, full=True),
    }


@router.post("/api/admin/public-jobs/{job_id}/approve")
def approve_admin_public_job(job_id: str, current_user: dict = Depends(get_current_admin_user)):
    try:
        return public_jobs.approve_public_job(job_id, current_user["id"])
    except public_jobs.PublicJobNotFound:
        raise HTTPException(status_code=404, detail="Job not found")
    except public_jobs.PublicJobNotPending as e:
        raise HTTPException(status_code=409, detail=f"Job is already {e.actual_status}")


class RejectPublicJobRequest(BaseModel):
    reason: str | None = None


@router.post("/api/admin/public-jobs/{job_id}/reject")
def reject_admin_public_job(
    job_id: str, body: RejectPublicJobRequest, current_user: dict = Depends(get_current_admin_user)
):
    try:
        return public_jobs.reject_public_job(job_id, current_user["id"], body.reason)
    except public_jobs.PublicJobNotFound:
        raise HTTPException(status_code=404, detail="Job not found")
    except public_jobs.PublicJobNotPending as e:
        raise HTTPException(status_code=409, detail=f"Job is already {e.actual_status}")
