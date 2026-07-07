"""One-shot retention sweep: deletes on-disk files for `done` jobs older
than RETENTION_DAYS (nobody's documents are guaranteed past this -- pricing
is pay-as-you-go with no plan tier that grants unlimited retention). The job
row itself is kept (id, duration_seconds, user_id, billed_cents,
timestamps) since usage/billing history still needs it -- only
document_path is nulled (it's the one thing route handlers use to decide
whether a document is servable) and deleted_at is set. source_path is left
as a historical string, not nulled -- it's a NOT NULL column and nothing
reads it once a job is done, so it's harmless as a record of where the
upload used to live.

Run via cron, not folded into worker.py's poll loop: that loop synchronously
blocks on run_job for the duration of video processing, and a slow cleanup
pass sharing that thread would delay picking up newly queued jobs. See
backend/README.md for the crontab line.

    docker compose run --rm api python retention.py
"""

import shutil
from datetime import datetime, timedelta, timezone

from app import jobs
from app.config import settings

RETENTION_DAYS = 7


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    eligible = jobs.list_jobs_eligible_for_retention(cutoff)
    print(f"Retention sweep: {len(eligible)} job(s) older than {RETENTION_DAYS} days to clean up", flush=True)

    for job in eligible:
        job_id = job["id"]
        shutil.rmtree(settings.OUTPUT_DIR / job_id, ignore_errors=True)
        shutil.rmtree(settings.UPLOADS_DIR / job_id, ignore_errors=True)
        jobs.update_job(job_id, document_path=None, deleted_at=datetime.now(timezone.utc))
        print(f"  cleaned up job {job_id} (created {job['created_at']})", flush=True)


if __name__ == "__main__":
    main()
