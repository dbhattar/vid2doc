"""Business logic for the public-showcase opt-in feature (see
routes/public_jobs.py, routes/admin.py's public-jobs endpoints). A user
opts a completed job_type=="video" job into a public, permanent listing in
exchange for a partial refund of billed_cents; an admin must approve it
before the refund is issued or it's publicly listed.

Archive-then-queue, not queue-then-archive: the S3 archive is uploaded
SYNCHRONOUSLY inside submit_public_consent, before the job ever enters the
"pending" moderation queue -- not at approval time. This means:
  - approve_public_job touches nothing outside Postgres (no S3 call, so no
    "refund succeeded but archive failed" or vice versa to reconcile).
  - retention.py needs no changes at all: submit_public_consent requires
    status=="done" and not yet deleted (same gate routes/share.py uses), so
    by construction every job that ever becomes "pending" already has a
    durable S3 copy before the 7-day sweep could ever touch its local files.

One tradeoff, deliberate and documented rather than hidden: because the
archive is written at opt-in (before any admin decision), a job's archived
files sit in the same public-read S3 prefix whether public_status is
"pending", "approved", or "rejected" -- they're just not *listed* anywhere
(routes/public_jobs.py's public showcase endpoints) until approved. This
mirrors the existing share_token model's risk shape (an unguessable
identifier -- there, a random token; here, job.id, a UUID -- gates an
otherwise-public URL). Revisit only if that turns out to be unacceptable;
the alternative (private-until-approved + an ACL flip on approval)
reintroduces the exact cross-system consistency problem this design avoids.
"""

import math
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from . import billing, jobs
from .config import settings
from .db import get_session
from .models import Job
from .s3_client import get_client as get_s3_client


class PublicArchiveUploadError(Exception):
    """Raised by upload_job_archive if any file fails to upload -- the
    caller (submit_public_consent) never persists pending-moderation state
    on this, so a job never enters the admin queue backed by a partial
    archive."""


class PublicJobNotFound(Exception):
    pass


class PublicJobNotPending(Exception):
    def __init__(self, actual_status: str | None):
        self.actual_status = actual_status
        super().__init__(f"Job is not pending (actual status: {actual_status!r})")


def archive_prefix_for(job_id: str) -> str:
    return f"public/{job_id}/"


def compute_refund_cents(billed_cents: int) -> int:
    """Shared by submit_public_consent (which locks this in at opt-in time)
    and routes/status.py (which shows it as a live preview -- "you'd get $X
    back" -- before the user has opted in at all, so the confirmation UI can
    show a real number instead of a vague percentage)."""
    return math.floor(billed_cents * settings.PUBLIC_CONSENT_REFUND_PERCENT / 100)


def _gather_archive_files(doc_dir: Path) -> list[Path]:
    """Same file set as routes/drive.py's upload_job_to_drive -- document.md
    plus docx/pdf/transcript.json when present, plus every image."""
    files = []
    for name in ("document.md", "document.docx", "document.pdf", "transcript.json"):
        path = doc_dir / name
        if path.is_file():
            files.append(path)
    images_dir = doc_dir / "images"
    if images_dir.is_dir():
        files.extend(sorted(p for p in images_dir.iterdir() if p.is_file()))
    return files


def upload_job_archive(job_id: str, doc_dir: Path, source_path: Path, prefix: str) -> str:
    """All-or-nothing: if any file fails partway through, delete whatever
    objects already succeeded and raise, rather than tolerating partial
    failure the way Drive's upload does -- this archive is unattended and
    meant to be permanent, so a partial one is worse than none.

    Uploads the generated document files AND the original source video
    (source_path) under the same prefix -- a showcased item is meant to
    show both, not just the document. Returns the video's filename *relative
    to prefix* (preserving source_path's original extension, since uploads
    aren't always .mp4) -- same convention as the hardcoded "document.md"
    etc. below, so routes/public_jobs.py's `base + filename` URL-building
    stays consistent instead of double-including the prefix.

    Public, not module-private: app/chat_jobs.py reuses this directly for
    its own (private-prefix) archive step -- the all-or-nothing upload
    logic is identical, only the prefix/visibility differs."""
    client = get_s3_client()
    files = _gather_archive_files(doc_dir)
    video_filename = f"source{source_path.suffix or '.mp4'}"
    video_key = f"{prefix}{video_filename}"
    uploaded_keys = []
    try:
        for path in files:
            key = f"{prefix}{path.relative_to(doc_dir)}"
            client.upload_file(str(path), settings.PUBLIC_ARCHIVE_S3_BUCKET, key)
            uploaded_keys.append(key)
        client.upload_file(str(source_path), settings.PUBLIC_ARCHIVE_S3_BUCKET, video_key)
        uploaded_keys.append(video_key)
    except Exception as e:
        for key in uploaded_keys:
            try:
                client.delete_object(Bucket=settings.PUBLIC_ARCHIVE_S3_BUCKET, Key=key)
            except Exception:
                pass  # best-effort cleanup only -- the outer raise is what matters
        raise PublicArchiveUploadError(f"Failed to archive job {job_id} to S3: {e}") from e
    return video_filename


def archive_file_exists(prefix: str, filename: str) -> bool:
    """Cheap existence check for an optional archived file (docx/pdf/
    transcript.json) -- used only by single-item detail responses, never by
    list responses (would be too many S3 calls for a paginated list)."""
    try:
        get_s3_client().head_object(Bucket=settings.PUBLIC_ARCHIVE_S3_BUCKET, Key=f"{prefix}{filename}")
        return True
    except Exception:
        return False


def delete_s3_archive(prefix: str | None) -> None:
    """Best-effort only -- used to clean up a rejected submission's archive
    (only *approved* content needs the forever-guarantee). An occasional
    orphaned object from a failed cleanup is an acceptable, minor storage
    cost, not a correctness issue."""
    if not prefix:
        return
    try:
        client = get_s3_client()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.PUBLIC_ARCHIVE_S3_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                client.delete_object(Bucket=settings.PUBLIC_ARCHIVE_S3_BUCKET, Key=obj["Key"])
    except Exception as e:
        print(f"Best-effort S3 archive cleanup failed for prefix {prefix}: {e}", flush=True)


def submit_public_consent(job: dict, doc_dir: Path) -> dict:
    """job is pre-validated by the caller (owned, job_type=="video",
    status=="done", not deleted, not already opted in) -- see
    routes/public_jobs.py. Uploads the archive FIRST and only persists
    pending-moderation state if that fully succeeds -- a job never enters
    the admin queue backed by a partial archive."""
    refund_cents = compute_refund_cents(job["billed_cents"])
    prefix = archive_prefix_for(job["id"])
    video_key = upload_job_archive(job["id"], doc_dir, Path(job["source_path"]), prefix)

    now = datetime.now(timezone.utc)
    jobs.update_job(
        job["id"],
        public_status="pending",
        public_consented_at=now,
        public_refund_cents=refund_cents,
        public_archive_prefix=prefix,
        public_video_key=video_key,
        public_archived_at=now,
    )
    return {"public_status": "pending", "public_refund_cents": refund_cents}


def approve_public_job(job_id: str, admin_user_id: str) -> dict:
    """Row-locked, all-in-one-transaction: locks the job row, verifies it's
    still "pending" *inside* that lock, and only then records the refund and
    flips status -- a second concurrent approve (double-click, two admins)
    blocks on the lock until the first commits, then sees "approved" and
    raises without touching the ledger. Touches nothing outside Postgres --
    the archive already exists (uploaded at opt-in), so there's no S3 call
    (and no partial-failure story to design around) here at all."""
    session = get_session()
    try:
        job = session.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one_or_none()
        if not job:
            raise PublicJobNotFound(job_id)
        if job.public_status != "pending":
            raise PublicJobNotPending(job.public_status)
        billing.record_public_refund(session, job.user_id, job.id, job.public_refund_cents or 0)
        job.public_status = "approved"
        job.public_reviewed_at = datetime.now(timezone.utc)
        job.public_reviewed_by = admin_user_id
        job.updated_at = datetime.now(timezone.utc)
        session.commit()
    except (PublicJobNotFound, PublicJobNotPending):
        session.rollback()
        raise
    finally:
        session.close()
    return jobs.get_job(job_id)


def reject_public_job(job_id: str, admin_user_id: str, reason: str | None) -> dict:
    """Same row-locked shape as approve_public_job, minus the refund. Best-
    effort deletes the archive after commit (see delete_s3_archive) -- only
    approved content needs the forever-guarantee."""
    session = get_session()
    try:
        job = session.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one_or_none()
        if not job:
            raise PublicJobNotFound(job_id)
        if job.public_status != "pending":
            raise PublicJobNotPending(job.public_status)
        archive_prefix = job.public_archive_prefix
        job.public_status = "rejected"
        job.public_reviewed_at = datetime.now(timezone.utc)
        job.public_reviewed_by = admin_user_id
        job.public_rejection_reason = reason
        job.updated_at = datetime.now(timezone.utc)
        session.commit()
    except (PublicJobNotFound, PublicJobNotPending):
        session.rollback()
        raise
    finally:
        session.close()

    delete_s3_archive(archive_prefix)
    return jobs.get_job(job_id)
