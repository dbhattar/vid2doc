from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import billing, jobs, users
from ..deps import get_current_admin_user

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
