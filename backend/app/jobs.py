import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from .db import get_session
from .models import Job


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "user_id": str(job.user_id) if job.user_id else None,
        "status": job.status,
        "progress_stage": job.progress_stage,
        "job_type": job.job_type,
        "title": job.title,
        "source_path": job.source_path,
        "source_url": job.source_url,
        "document_path": job.document_path,
        "duration_seconds": job.duration_seconds,
        "source_size_bytes": job.source_size_bytes,
        "billed_cents": job.billed_cents,
        "client_ip": job.client_ip,
        "share_token": job.share_token,
        "aspect_ratio": job.aspect_ratio,
        "video_template": job.video_template,
        "stock_media_provider": job.stock_media_provider,
        "cancel_requested": job.cancel_requested,
        "extract_frames": job.extract_frames,
        "error_message": job.error_message,
        "deleted_at": job.deleted_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def create_job(
    job_id: str,
    source_path: str | None,
    user_id: str | uuid.UUID | None = None,
    duration_seconds: float | None = None,
    size_bytes: int | None = None,
    billed_cents: int = 0,
    title: str | None = None,
    job_type: str = "video",
    client_ip: str | None = None,
    source_url: str | None = None,
    aspect_ratio: str = "16:9",
    extract_frames: bool = True,
) -> None:
    session = get_session()
    try:
        session.add(
            Job(
                id=job_id,
                user_id=user_id,
                status="queued",
                source_path=source_path,
                source_url=source_url,
                duration_seconds=duration_seconds,
                source_size_bytes=size_bytes,
                billed_cents=billed_cents,
                title=title,
                job_type=job_type,
                client_ip=client_ip,
                aspect_ratio=aspect_ratio,
                extract_frames=extract_frames,
            )
        )
        session.commit()
    finally:
        session.close()


def get_job(job_id: str) -> dict | None:
    session = get_session()
    try:
        job = session.get(Job, job_id)
        return _job_to_dict(job) if job else None
    finally:
        session.close()


def get_job_by_share_token(token: str) -> dict | None:
    session = get_session()
    try:
        job = session.query(Job).filter_by(share_token=token).one_or_none()
        return _job_to_dict(job) if job else None
    finally:
        session.close()


def claim_next_queued_job() -> dict | None:
    """Atomically claims the oldest queued job so multiple worker replicas
    never process the same job twice. Postgres's SELECT ... FOR UPDATE SKIP
    LOCKED lets a second worker skip a row a first worker already has locked,
    rather than blocking on it or racing it (the previous SQLite version used
    a single atomic UPDATE instead, since SQLite has no row-level locking)."""
    session = get_session()
    try:
        job = session.execute(
            select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1).with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if not job:
            return None
        job.status = "processing"
        job.updated_at = _now()
        session.commit()
        return _job_to_dict(job)
    finally:
        session.close()


def set_cancel_requested(job_id: str) -> None:
    """Flags a job for cancellation -- pipeline.py's _check_not_cancelled
    picks this up at the next stage boundary for a job actually being
    processed. A no-op signal for a queued/awaiting_review job (nothing is
    running yet to notice it), which is why routes/jobs.py's cancel endpoint
    also calls cancel_if_not_processing for those statuses."""
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            return
        job.cancel_requested = True
        job.updated_at = _now()
        session.commit()
    finally:
        session.close()


def cancel_if_not_processing(job_id: str) -> bool:
    """Atomically flips a still-queued or awaiting-review job straight to
    status="cancelled" -- returns True if this call actually made the
    change. Both statuses mean nothing is actively running for this job
    right now (the worker hasn't claimed a queued job yet, and never
    touches an awaiting_review job until the user submits their review), so
    there's no in-flight work to cooperatively wait out -- cancellation is
    immediate. Returns False if the row had already moved on by the time
    this ran (e.g. the worker claimed it in the same instant it was
    queued) -- cancel_requested, set by the caller beforehand, covers that
    race: pipeline.py's own checkpoints will catch it moments later."""
    session = get_session()
    try:
        result = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(["queued", "awaiting_review"]))
            .values(status="cancelled", updated_at=_now())
        )
        session.commit()
        return result.rowcount > 0
    finally:
        session.close()


def list_processing_jobs() -> list[dict]:
    """Every job currently marked "processing" -- used by worker.py's
    startup recovery sweep. In this single-worker-container deployment,
    only the worker's own current job should ever be "processing", so
    anything found here at startup was left behind by a previous worker
    process that died mid-job (a crash, an OOM kill, or a redeploy/restart
    while it had a job in flight) -- there's no live subprocess supervising
    it anymore, and claim_next_queued_job will never reclaim it (it only
    ever looks at "queued" rows), so without this sweep it would stay stuck
    in "processing" forever, cancel_requested or not."""
    session = get_session()
    try:
        rows = session.query(Job).filter(Job.status == "processing").all()
        return [_job_to_dict(j) for j in rows]
    finally:
        session.close()


def update_job(job_id: str, **fields) -> None:
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = _now()
        session.commit()
    finally:
        session.close()


def list_jobs_for_user(
    user_id: str | uuid.UUID,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    job_type: str | None = None,
) -> list[dict]:
    session = get_session()
    try:
        query = session.query(Job).filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
        if job_type:
            query = query.filter_by(job_type=job_type)
        rows = query.order_by(Job.created_at.desc()).limit(limit).offset(offset).all()
        return [_job_to_dict(j) for j in rows]
    finally:
        session.close()


def count_jobs_for_user(
    user_id: str | uuid.UUID, status: str | None = None, job_type: str | None = None
) -> int:
    session = get_session()
    try:
        query = session.query(Job).filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
        if job_type:
            query = query.filter_by(job_type=job_type)
        return query.count()
    finally:
        session.close()


def delete_job(job_id: str) -> None:
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if job:
            session.delete(job)
            session.commit()
    finally:
        session.close()


def list_jobs_eligible_for_retention(cutoff: datetime) -> list[dict]:
    """`done` jobs created before `cutoff` that haven't already been cleaned
    up. Retention applies to everyone -- there's no plan tier anymore that
    gets unlimited retention. `awaiting_review` jobs are swept the same way:
    a frame review nobody ever finished never produces a usable document
    either, so it shouldn't hold onto disk space forever just because it
    never technically "finished" (see retention.py for how the two statuses
    are handled differently once found)."""
    session = get_session()
    try:
        rows = (
            session.query(Job)
            .filter(Job.status.in_(["done", "awaiting_review"]), Job.created_at < cutoff, Job.deleted_at.is_(None))
            .all()
        )
        return [_job_to_dict(j) for j in rows]
    finally:
        session.close()


def count_jobs_by_type() -> dict:
    """{"video": N, "audio": N} across every job regardless of status --
    for the admin dashboard's "videos/audio processed" count."""
    session = get_session()
    try:
        rows = session.query(Job.job_type, func.count(Job.id)).group_by(Job.job_type).all()
        return {job_type: count for job_type, count in rows}
    finally:
        session.close()


def total_source_size_bytes() -> int:
    session = get_session()
    try:
        total = session.query(func.coalesce(func.sum(Job.source_size_bytes), 0)).scalar()
        return int(total or 0)
    finally:
        session.close()
