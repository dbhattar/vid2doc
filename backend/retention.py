"""One-shot retention sweep: deletes on-disk files for `done` jobs older
than RETENTION_DAYS (nobody's documents are guaranteed past this -- pricing
is pay-as-you-go with no plan tier that grants unlimited retention). The job
row itself is kept (id, duration_seconds, user_id, billed_cents,
timestamps) since usage/billing history still needs it -- only
document_path is nulled (it's the one thing route handlers use to decide
whether a document is servable) and deleted_at is set. source_path is left
as a historical string, not nulled -- nothing reads it once a job is done,
so it's harmless as a record of where the upload used to live.

`awaiting_review` jobs (a video paused for frame review, see pipeline.py) are
swept too, but handled differently: since no usable document was ever
produced, the charge gets refunded and the job is marked `failed` with a
clear message, instead of staying `awaiting_review` with thumbnails that
would otherwise 404 once their files are gone.

Anonymous trial jobs (routes/trial.py) get a completely separate, much
shorter pass (see _cleanup_trial_jobs): a hard delete after TRIAL_RETENTION_HOURS,
row and all -- there's no charge to refund and no billing history to keep.

Run via cron, not folded into worker.py's poll loop: that loop synchronously
blocks on run_job for the duration of video processing, and a slow cleanup
pass sharing that thread would delay picking up newly queued jobs. See
backend/README.md for the crontab line.

    docker compose run --rm api python retention.py
"""

import shutil
from datetime import datetime, timedelta, timezone

from app import billing, emails, jobs
from app.config import settings

RETENTION_DAYS = 7


def _cleanup_trial_jobs() -> None:
    """Anonymous trial jobs (user_id IS NULL, see routes/trial.py) get a much
    shorter, unconditional hard delete instead of the soft-delete-and-keep-
    the-row treatment above -- there's no charge to refund and no billing
    history worth preserving for a job nobody ever paid for."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.TRIAL_RETENTION_HOURS)
    eligible = jobs.list_trial_jobs_eligible_for_cleanup(cutoff)
    print(f"Trial cleanup: {len(eligible)} job(s) older than {settings.TRIAL_RETENTION_HOURS}h to purge", flush=True)

    for job in eligible:
        job_id = job["id"]
        shutil.rmtree(settings.OUTPUT_DIR / job_id, ignore_errors=True)
        shutil.rmtree(settings.UPLOADS_DIR / job_id, ignore_errors=True)
        jobs.delete_job(job_id)
        print(f"  purged trial job {job_id} (created {job['created_at']}, was {job['status']})", flush=True)


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    eligible = jobs.list_jobs_eligible_for_retention(cutoff)
    print(f"Retention sweep: {len(eligible)} job(s) older than {RETENTION_DAYS} days to clean up", flush=True)

    for job in eligible:
        job_id = job["id"]
        shutil.rmtree(settings.OUTPUT_DIR / job_id, ignore_errors=True)
        shutil.rmtree(settings.UPLOADS_DIR / job_id, ignore_errors=True)

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
        else:
            jobs.update_job(job_id, document_path=None, deleted_at=datetime.now(timezone.utc))

        print(f"  cleaned up job {job_id} (created {job['created_at']}, was {job['status']})", flush=True)

    _cleanup_trial_jobs()


if __name__ == "__main__":
    main()
