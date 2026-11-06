"""One-shot retention sweep, three parts:

1. `done` jobs older than RETENTION_DAYS: their on-disk files are deleted
   (nobody's documents are guaranteed past this -- pricing is pay-as-you-go
   with no plan tier that grants unlimited retention). The job row itself is
   kept (id, duration_seconds, user_id, billed_cents, timestamps) since
   usage/billing history still needs it -- only document_path is nulled (it's
   the one thing route handlers use to decide whether a document is servable)
   and deleted_at is set. source_path is left as a historical string, not
   nulled -- nothing reads it once a job is done, so it's harmless as a record
   of where the upload used to live.

   Exception: a done job with an S3 archive (a showcase submission or a
   chat-enabled job) is NOT marked deleted. Its local files are freed like any
   other, but it stays servable -- the owner's routes rebuild the document
   from the archive on demand (see app/archive_access.py).

2. `awaiting_review` jobs (a video paused for frame review, see pipeline.py)
   are swept too, but handled differently: since no usable document was ever
   produced, the charge gets refunded and the job is marked `failed` with a
   clear message, instead of staying `awaiting_review` with thumbnails that
   would otherwise 404 once their files are gone.

3. `failed`/`cancelled` jobs older than RETENTION_DAYS, and orphaned folders
   (a folder under uploads/ or output/ with no job row at all -- e.g. an
   upload that was rejected after its file was written) older than
   RETENTION_DAYS: files only, nothing to refund. Without this, anything that
   didn't finish successfully would sit on disk forever.

Run via cron, not folded into worker.py's poll loop: that loop synchronously
blocks on run_job for the duration of video processing, and a slow cleanup
pass sharing that thread would delay picking up newly queued jobs. Nothing
starts it automatically -- install the cron entry with
`fab ... install-retention-cron` (see deploy/fabfile.py), or see
backend/README.md. To see what it would delete without deleting anything:

    docker compose run --rm -T api python retention.py --dry-run
"""

import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import archive_access, billing, emails, jobs
from app.config import settings

RETENTION_DAYS = 7

_JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def _remove_job_dirs(job_id: str, dry_run: bool) -> int:
    """Deletes (or, in a dry run, just measures) a job's uploads/ and output/
    folders. Returns the bytes involved."""
    freed = 0
    for base in (settings.OUTPUT_DIR, settings.UPLOADS_DIR):
        path = base / job_id
        if path.is_dir():
            freed += _dir_size(path)
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
    return freed


def _sweep_orphans(cutoff_ts: float, dry_run: bool) -> tuple[int, int]:
    """Job-id-shaped folders under uploads/ and output/ that no job row owns
    and that haven't been touched since the cutoff. The age check is what
    keeps this from racing an in-flight upload whose row isn't written yet."""
    candidates: list[tuple[Path, str]] = []
    for base in (settings.UPLOADS_DIR, settings.OUTPUT_DIR):
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            try:
                if entry.is_dir() and _JOB_ID_RE.match(entry.name) and entry.stat().st_mtime < cutoff_ts:
                    candidates.append((entry, entry.name))
            except OSError:
                continue
    known = jobs.existing_job_ids(sorted({name for _, name in candidates}))
    count = freed = 0
    for path, name in candidates:
        if name in known:
            continue
        size = _dir_size(path)
        if not dry_run:
            shutil.rmtree(path, ignore_errors=True)
        count += 1
        freed += size
        print(f"  {'would remove' if dry_run else 'removed'} orphaned folder {path} ({_human(size)})", flush=True)
    return count, freed


def main(dry_run: bool = False) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    verb = "would clean up" if dry_run else "cleaned up"
    total_freed = 0

    eligible = jobs.list_jobs_eligible_for_retention(cutoff)
    print(f"Retention sweep{' (DRY RUN -- nothing is deleted)' if dry_run else ''}: "
          f"{len(eligible)} done/awaiting-review job(s) older than {RETENTION_DAYS} days", flush=True)
    for job in eligible:
        job_id = job["id"]
        archived = job["status"] == "done" and archive_access.archive_prefix(job) is not None
        freed = _remove_job_dirs(job_id, dry_run)
        total_freed += freed
        if not dry_run:
            if job["status"] == "awaiting_review":
                if job.get("user_id") and job.get("billed_cents"):
                    billing.refund_job_charge(job["user_id"], job_id, job["billed_cents"])
                jobs.update_job(
                    job_id,
                    status="failed",
                    progress_stage=None,
                    error_message="Review wasn't completed within 7 days",
                    document_path=None,
                    deleted_at=datetime.now(timezone.utc),
                )
                emails.notify_job_status_change(job_id)
            elif not archived:
                jobs.update_job(job_id, document_path=None, deleted_at=datetime.now(timezone.utc))
        if archived and not freed:
            continue  # nothing local to free, and nothing else changes for it
        note = ", archived" if archived else ""
        print(f"  {verb} job {job_id} ({_human(freed)}{note}; created {job['created_at']}, was {job['status']})", flush=True)

    stale = jobs.list_stale_failed_jobs(cutoff)
    print(f"{len(stale)} failed/cancelled job(s) older than {RETENTION_DAYS} days", flush=True)
    for job in stale:
        freed = _remove_job_dirs(job["id"], dry_run)
        total_freed += freed
        if not dry_run:
            jobs.update_job(job["id"], document_path=None, deleted_at=datetime.now(timezone.utc))
        print(f"  {verb} job {job['id']} ({_human(freed)}; created {job['created_at']}, was {job['status']})", flush=True)

    orphan_count, orphan_freed = _sweep_orphans(time.time() - RETENTION_DAYS * 86400, dry_run)
    total_freed += orphan_freed
    print(f"{orphan_count} orphaned folder(s) with no job row", flush=True)

    print(f"Total {'that would be freed' if dry_run else 'freed'}: {_human(total_freed)}", flush=True)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv[1:])
