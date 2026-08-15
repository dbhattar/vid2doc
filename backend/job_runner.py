"""Standalone entry point that runs exactly one job, in its own OS process --
spawned by worker.py (never invoked directly) so a job can be forcibly killed,
including whatever ffmpeg subprocess or LLM API call it's currently blocked
on, without needing any cooperation from the pipeline code itself. See
worker.py's docstring for why this is a separate process rather than an
in-process function call.
"""

import sys

from app import jobs
from app.pipeline import run_job


def main() -> None:
    job_id = sys.argv[1]
    job = jobs.get_job(job_id)
    if job is None:
        print(f"job_runner: job {job_id} not found", flush=True)
        sys.exit(1)
    run_job(job)


if __name__ == "__main__":
    main()
