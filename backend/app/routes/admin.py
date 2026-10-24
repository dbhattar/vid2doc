from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import activity, announcements, billing, feedback, jobs, public_jobs, users
from ..config import settings
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


def _set_public_hidden(job_id: str, hidden: bool) -> dict:
    """Shared by hide/unhide below -- a display-only flag flip, not a money-
    moving state transition like approve/reject, so no row-locking (see
    jobs.update_job's own docstring on when the plain get+setattr+commit
    shape is sufficient). Only meaningful for an "approved" job -- pending/
    rejected items never appear on the showcase regardless, so there's
    nothing for admin to hide/unhide on those."""
    job = jobs.get_job(job_id)
    if not job or job["public_status"] != "approved":
        raise HTTPException(status_code=404, detail="Job not found")
    jobs.update_job(job_id, public_hidden=hidden)
    return jobs.get_job(job_id)


@router.post("/api/admin/public-jobs/{job_id}/hide")
def hide_admin_public_job(job_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Excludes an approved item from the homepage carousel -- see
    Job.public_hidden's own comment. Does not touch public_status, the
    refund, or the S3 archive; the direct permalink keeps working."""
    return _set_public_hidden(job_id, True)


@router.post("/api/admin/public-jobs/{job_id}/unhide")
def unhide_admin_public_job(job_id: str, current_user: dict = Depends(get_current_admin_user)):
    return _set_public_hidden(job_id, False)


class AnnouncementRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=announcements.MAX_SUBJECT_CHARS)
    body: str = Field(min_length=1, max_length=announcements.MAX_BODY_CHARS)
    # True sends only to the calling admin -- a preview before the real send.
    test: bool = False
    # None means everyone who hasn't unsubscribed; a list means just those users.
    user_ids: list[str] | None = Field(default=None, max_length=100_000)
    tag: str = announcements.DEFAULT_TAG
    cta_label: str | None = Field(default=None, max_length=60)
    cta_url: str | None = Field(default=None, max_length=2000)


def _validated_cta(body: "AnnouncementRequest") -> None:
    if body.tag not in announcements.TAGS:
        raise HTTPException(status_code=400, detail="Unknown tag.")
    try:
        announcements.validate_cta(body.cta_label, body.cta_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _require_mailgun() -> None:
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        raise HTTPException(status_code=503, detail="Email isn't configured (MAILGUN_API_KEY/MAILGUN_DOMAIN).")


@router.get("/api/admin/announcements/audience")
def get_announcement_audience(current_user: dict = Depends(get_current_admin_user)):
    return {"recipient_count": len(users.list_announcement_recipients())}


@router.post("/api/admin/announcements/preview")
def preview_admin_announcement(body: AnnouncementRequest, current_user: dict = Depends(get_current_admin_user)):
    """Renders the email exactly as the calling admin would receive it."""
    _validated_cta(body)
    html_body, _, _ = announcements.render_announcement(
        current_user, body.subject, body.body, body.tag, body.cta_label, body.cta_url
    )
    return {"html": html_body}


@router.get("/api/admin/announcements")
def list_admin_announcements(current_user: dict = Depends(get_current_admin_user)):
    return {"announcements": announcements.list_recent_announcements()}


@router.post("/api/admin/announcements")
def send_admin_announcement(body: AnnouncementRequest, current_user: dict = Depends(get_current_admin_user)):
    """Test sends go out inline (one email, and the admin wants to know it
    worked). A real send only queues one delivery per recipient -- the worker
    sends them individually, with a delay between each (see
    app/announcements.py) -- so the response says how many are queued, and
    GET /api/admin/announcements shows progress."""
    _require_mailgun()
    _validated_cta(body)
    if body.test:
        sent = announcements.send_announcement_to_user(
            current_user, body.subject, body.body, body.tag, body.cta_label, body.cta_url
        )
        if not sent:
            raise HTTPException(status_code=502, detail="Mailgun rejected the test email.")
        return {"test": True, "recipient_count": 1}
    if body.user_ids is not None and not body.user_ids:
        raise HTTPException(status_code=400, detail="Select at least one user.")
    announcement_id, recipient_count = announcements.queue_announcement(
        body.subject, body.body, current_user["id"], body.user_ids, body.tag, body.cta_label, body.cta_url
    )
    if recipient_count == 0:
        raise HTTPException(status_code=400, detail="None of the selected users can receive announcements.")
    return {"test": False, "id": announcement_id, "recipient_count": recipient_count}
