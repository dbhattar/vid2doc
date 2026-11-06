"""One-off: un-delete jobs that retention.py marked deleted even though they
have an S3 archive (a showcase submission or a chat-enabled job), so they
show up on the dashboard again. Their documents are rebuilt from the archive
on first access (see app/archive_access.py).

Dry run by default; pass --apply to change anything:

    docker compose run --rm -T api python scripts/restore_archived_jobs.py
    docker compose run --rm -T api python scripts/restore_archived_jobs.py --apply
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app import archive_access, jobs
from app.db import get_session
from app.models import Job


def main(apply: bool) -> None:
    session = get_session()
    try:
        ids = session.execute(
            select(Job.id).where(Job.status == "done", Job.deleted_at.is_not(None))
        ).scalars().all()
    finally:
        session.close()

    restored = skipped = 0
    for job_id in ids:
        job = jobs.get_job(job_id)
        if not job or not archive_access.archive_prefix(job):
            continue
        if not archive_access.archive_file_exists(job, "document.md"):
            print(f"  skip {job_id}: archive has no document.md", flush=True)
            skipped += 1
            continue
        print(f"  {'restore' if apply else 'would restore'} {job_id} ({job['title']})", flush=True)
        if apply:
            jobs.update_job(job_id, deleted_at=None)
        restored += 1
    print(f"{restored} {'restored' if apply else 'restorable'}, {skipped} skipped", flush=True)


if __name__ == "__main__":
    main(apply="--apply" in sys.argv[1:])
