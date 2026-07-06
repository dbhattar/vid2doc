"""Worker process: polls the shared SQLite jobs table and runs the pipeline
for each queued job. Runs as its own container/service in docker-compose so
video processing never blocks the API's HTTP request handling."""

import time

from app import jobs
from app.config import settings
from app.pipeline import run_job


def main() -> None:
    print("Worker started, polling for jobs...", flush=True)
    while True:
        job = jobs.claim_next_queued_job()
        if job is None:
            time.sleep(settings.WORKER_POLL_SECONDS)
            continue

        print(f"Processing job {job['id']}", flush=True)
        run_job(job)
        final = jobs.get_job(job["id"])
        print(f"Job {job['id']} finished with status={final['status']}", flush=True)


if __name__ == "__main__":
    main()
