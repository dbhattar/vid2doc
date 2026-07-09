import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import billing, jobs
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


@router.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Re-runs a failed job against the same uploaded video, without needing
    a re-upload. Modeled as a fresh job (new id, own charge) rather than
    resetting the failed row in place -- keeps both attempts visible in the
    jobs list, and reuses the exact charge/refund path convert_to_doc already
    has instead of a separate billing code path just for retries."""
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "failed":
        raise HTTPException(status_code=400, detail="Only failed jobs can be retried")
    if job["duration_seconds"] is None:
        raise HTTPException(status_code=400, detail="Missing video duration -- please upload it again")

    source_path = Path(job["source_path"])
    if not source_path.exists():
        raise HTTPException(status_code=400, detail="Original video is no longer available -- please upload it again")

    new_job_id = str(uuid.uuid4())
    try:
        billed_cents = billing.charge_for_job(current_user["id"], new_job_id, job["duration_seconds"])
    except billing.InsufficientBalanceError as e:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient balance: this video costs ${e.required_cents / 100:.2f}, "
                f"you have ${e.balance_cents / 100:.2f}. Add funds at /settings/billing."
            ),
        )

    jobs.create_job(
        new_job_id,
        str(source_path),
        user_id=current_user["id"],
        duration_seconds=job["duration_seconds"],
        billed_cents=billed_cents,
    )
    return build_job_response(jobs.get_job(new_job_id), request)
