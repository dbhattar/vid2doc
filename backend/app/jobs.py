import uuid
from datetime import datetime, timezone

from sqlalchemy import select

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
        "source_path": job.source_path,
        "document_path": job.document_path,
        "duration_seconds": job.duration_seconds,
        "billed_overage_cents": job.billed_overage_cents,
        "error_message": job.error_message,
        "deleted_at": job.deleted_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def create_job(
    job_id: str,
    source_path: str,
    user_id: str | uuid.UUID | None = None,
    duration_seconds: float | None = None,
) -> None:
    session = get_session()
    try:
        session.add(
            Job(
                id=job_id,
                user_id=user_id,
                status="queued",
                source_path=source_path,
                duration_seconds=duration_seconds,
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
