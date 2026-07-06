from fastapi import APIRouter, Depends, Query, Request

from .. import jobs
from ..deps import get_current_user
from .status import build_job_response

router = APIRouter()


@router.get("/api/jobs")
def list_jobs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    job_list = jobs.list_jobs_for_user(current_user["id"], limit=limit, offset=offset)
    total = jobs.count_jobs_for_user(current_user["id"])
    return {"jobs": [build_job_response(job, request) for job in job_list], "total": total}
