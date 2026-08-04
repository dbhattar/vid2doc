import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import billing, jobs
from ..config import settings
from ..deps import get_current_user
from .status import build_job_response

router = APIRouter()


@router.get("/api/jobs")
def list_jobs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="Filter to one status, e.g. status=done"),
    job_type: str | None = Query(default=None, description="Filter to one job type, e.g. job_type=video"),
    current_user: dict = Depends(get_current_user),
):
    job_list = jobs.list_jobs_for_user(
        current_user["id"], limit=limit, offset=offset, status=status, job_type=job_type
    )
    total = jobs.count_jobs_for_user(current_user["id"], status=status, job_type=job_type)
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
        raise HTTPException(status_code=400, detail="Missing duration -- please upload it again")

    # A direct upload (or a YouTube import that already finished downloading
    # before some later stage failed) has source_path set -- reuse that file
    # as-is. A YouTube import that failed before/during its own download has
    # source_path=None and source_url set instead -- retry by re-queuing the
    # download rather than requiring a re-upload (see pipeline.py's
    # _download_if_needed).
    new_source_path: str | None = None
    if job["source_path"]:
        source_path = Path(job["source_path"])
        if not source_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Original {job['job_type']} file is no longer available -- please upload it again",
            )
        new_source_path = str(source_path)
    elif not job["source_url"]:
        raise HTTPException(status_code=400, detail="Missing source -- please upload it again")

    new_job_id = str(uuid.uuid4())
    try:
        billed_cents = billing.charge_for_job(
            current_user["id"], new_job_id, job["duration_seconds"], job_type=job["job_type"]
        )
    except billing.InsufficientBalanceError as e:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient balance: this costs ${e.required_cents / 100:.2f}, "
                f"you have ${e.balance_cents / 100:.2f}. Add funds at /settings/billing."
            ),
        )

    jobs.create_job(
        new_job_id,
        new_source_path,
        source_url=job["source_url"] if not new_source_path else None,
        user_id=current_user["id"],
        duration_seconds=job["duration_seconds"],
        size_bytes=job["source_size_bytes"],
        billed_cents=billed_cents,
        title=job["title"],
        job_type=job["job_type"],
    )
    return build_job_response(jobs.get_job(new_job_id), request)


@router.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """Removes a failed job -- it already refunded its charge in full (see
    pipeline.run_job's except block), produced no usable document, and just
    clutters the jobs list otherwise. Also allowed for a job sitting in
    "awaiting_review" (a video paused for frame review) -- same reasoning as
    retention.py's 7-day sweep for an abandoned review: no usable document
    was ever produced, so this refunds the original charge too, rather than
    making "wait for the sweep" the only way to get money back for a job
    you've decided not to finish. There's no risk of deleting a job someone's
    still waiting on or a document someone still needs, since both statuses
    mean nothing downstream depends on this job anymore."""
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("failed", "awaiting_review"):
        raise HTTPException(status_code=400, detail="Only failed or awaiting-review jobs can be deleted")

    if job["status"] == "awaiting_review" and job.get("user_id") and job.get("billed_cents"):
        billing.refund_job_charge(job["user_id"], job_id, job["billed_cents"])

    shutil.rmtree(settings.OUTPUT_DIR / job_id, ignore_errors=True)
    # Derived from job_id, not job["source_path"] (which is None for a
    # YouTube import that failed before ever downloading anything) -- every
    # job's upload dir is always settings.UPLOADS_DIR/<job_id> by convention
    # (see routes/convert.py, routes/audio.py, pipeline.py's
    # _download_if_needed), so this works whether or not source_path is set.
    shutil.rmtree(settings.UPLOADS_DIR / job_id, ignore_errors=True)
    jobs.delete_job(job_id)
