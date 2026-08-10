import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

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


def count_trial_jobs_from_ip_since(client_ip: str, since: datetime) -> int:
    """Basis of routes/trial.py's per-IP daily cap -- counts anonymous
    (user_id IS NULL) jobs from this IP created after `since`, regardless of
    status, so a job that's still processing (or even failed) still counts
    against the cap same as a finished one would."""
    session = get_session()
    try:
        return (
            session.query(Job)
            .filter(Job.user_id.is_(None), Job.client_ip == client_ip, Job.created_at >= since)
            .count()
        )
    finally:
        session.close()


def list_trial_jobs_eligible_for_cleanup(cutoff: datetime) -> list[dict]:
    """Anonymous trial jobs older than `cutoff`, any status -- unlike real
    users' jobs (list_jobs_eligible_for_retention), these are hard-deleted
    entirely (see retention.py), not soft-deleted, since no charge was ever
    made and there's no billing history worth preserving."""
    session = get_session()
    try:
        rows = session.query(Job).filter(Job.user_id.is_(None), Job.created_at < cutoff).all()
        return [_job_to_dict(j) for j in rows]
    finally:
        session.close()


def count_trial_jobs() -> int:
    """Total anonymous trial jobs (see routes/trial.py) currently in the
    table -- naturally bounded, since retention.py hard-deletes them a few
    hours after creation. For the admin dashboard's quick-glance stat."""
    session = get_session()
    try:
        return session.query(Job).filter(Job.user_id.is_(None)).count()
    finally:
        session.close()


def list_trial_jobs(limit: int = 200) -> list[dict]:
    """Anonymous trial jobs, most recent first -- gives an admin visibility
    into free-trial usage (and abuse patterns, via client_ip) that would
    otherwise be invisible, since these never show up in any per-user view."""
    session = get_session()
    try:
        rows = (
            session.query(Job)
            .filter(Job.user_id.is_(None))
            .order_by(Job.created_at.desc())
            .limit(limit)
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
