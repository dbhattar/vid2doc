"""Worker process: polls the shared jobs table and runs each job to
completion. Runs as its own container/service in docker-compose so video
processing never blocks the API's HTTP request handling.

Each job runs in its own OS process (job_runner.py), not as an in-process
function call -- this is what makes true, instant cancellation possible.
pipeline.py's own cooperative cancellation checks (_check_not_cancelled) are
a cheap fast path that fires cleanly at a stage boundary, but they can't
interrupt a blocking ffmpeg subprocess or LLM API call already in flight.
Running each job in its own process group lets this supervisor forcibly
kill the whole thing -- the job's Python process AND any ffmpeg child it
spawned -- the moment cancel_requested is noticed, regardless of what it's
currently blocked on.
"""

import os
import signal
import subprocess
import sys
import time

from app import billing, emails, jobs
from app.config import settings

CANCEL_POLL_SECONDS = 1.0
# Given to a killed process group to exit on its own (ffmpeg handles SIGTERM
# by finalizing its output cleanly) before escalating to SIGKILL -- short,
# since the output is being discarded either way and cancellation should
# feel close to instant.
KILL_GRACE_PERIOD_SECONDS = 2.0


def _finalize_stale_cancel(job_id: str) -> bool:
    """Called both right after we've killed a job's process, and after
    watching one exit on its own -- in both cases there's a genuine race
    between this job's own cooperative _check_not_cancelled calls and the
    API request that set cancel_requested, so by the time we get here the
    job could be sitting in "processing" (really was killed, but the
    process never got a chance to update its own status) or
    "awaiting_review" (the process finished its own cleanup and paused an
    instant before the kill/check could land, so there's nothing left
    server-side to interrupt). Both mean the same thing: cancellation was
    requested and never actually resolved. Returns True if it did anything,
    so callers can tell "already handled" apart from "nothing to do"."""
    job = jobs.get_job(job_id)
    if not job or not job["cancel_requested"] or job["status"] not in ("processing", "awaiting_review"):
        return False
    # progress_stage deliberately left untouched (whatever it was last set
    # to), same reasoning as pipeline.py's own cooperative JobCancelled path.
    jobs.update_job(job_id, status="cancelled")
    if job.get("user_id") and job.get("billed_cents"):
        billing.refund_job_charge(job["user_id"], job_id, job["billed_cents"])
    emails.notify_job_status_change(job_id)
    return True


def _run_job(job_id: str) -> None:
    # start_new_session=True makes this subprocess its own process group
    # leader (pgid == pid) -- any ffmpeg call it makes inherits that same
    # group, so killing the group catches both in one shot.
    proc = subprocess.Popen([sys.executable, "job_runner.py", job_id], start_new_session=True)
    pgid = proc.pid

    while proc.poll() is None:
        current = jobs.get_job(job_id)
        if current and current["cancel_requested"]:
            print(f"Cancelling job {job_id} (pid {proc.pid})...", flush=True)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=KILL_GRACE_PERIOD_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait()
            # The process is dead either way, but it may have raced past us
            # and already written "awaiting_review" (or even "done"/"failed"
            # on its own merits) before actually dying -- _finalize_stale_cancel
            # only overrides it to "cancelled" if that didn't happen.
            _finalize_stale_cancel(job_id)
            return
        time.sleep(CANCEL_POLL_SECONDS)

    # Exited on its own -- pipeline.py (run_job's own try/except, in the
    # child process) already recorded done/failed/cancelled in the common
    # case. _finalize_stale_cancel covers the race where cancellation was
    # requested too late for any single _check_not_cancelled call to catch,
    # and the job paused for review instead of stopping -- nothing
    # server-side is "running" for a paused job, so no later poll would
    # otherwise notice a still-pending cancel_requested on its own.
    if _finalize_stale_cancel(job_id):
        return

    final = jobs.get_job(job_id)
    if final and final["status"] == "processing":
        # Not cancellation-related: the child crashed before it ever
        # reached its own except block (e.g. an OOM kill) -- guard against
        # a job stuck in "processing" forever with no one left to finish it.
        jobs.update_job(job_id, status="failed", error_message="Worker process exited unexpectedly")
        if final.get("user_id") and final.get("billed_cents"):
            billing.refund_job_charge(final["user_id"], job_id, final["billed_cents"])
        emails.notify_job_status_change(job_id)


def _recover_orphaned_processing_jobs() -> None:
    """Runs once at startup, before polling begins. This worker just came
    up, so anything already marked "processing" (see jobs.list_processing_jobs)
    was left behind by a previous worker process that died mid-job --
    there's no live subprocess supervising it anymore, and it would
    otherwise stay stuck in "processing" forever, cancel_requested or not.
    Recovers each one: "cancelled" if the user had already asked to cancel
    it, "failed" (a genuine interruption, not the user's fault) otherwise --
    either way, refunded, never left stuck."""
    for job in jobs.list_processing_jobs():
        job_id = job["id"]
        if job["cancel_requested"]:
            print(f"Recovering orphaned job {job_id} as cancelled (was at {job['progress_stage']})", flush=True)
            jobs.update_job(job_id, status="cancelled")
        else:
            print(f"Recovering orphaned job {job_id} as failed (was at {job['progress_stage']})", flush=True)
            jobs.update_job(
                job_id,
                status="failed",
                error_message="Processing was interrupted (the worker restarted mid-job) -- please try again.",
            )
        if job.get("user_id") and job.get("billed_cents"):
            billing.refund_job_charge(job["user_id"], job_id, job["billed_cents"])
        emails.notify_job_status_change(job_id)


def main() -> None:
    print("Worker started, polling for jobs...", flush=True)
    _recover_orphaned_processing_jobs()
    while True:
        job = jobs.claim_next_queued_job()
        if job is None:
            time.sleep(settings.WORKER_POLL_SECONDS)
            continue

        print(f"Processing job {job['id']}", flush=True)
        _run_job(job["id"])
        final = jobs.get_job(job["id"])
        print(f"Job {job['id']} finished with status={final['status']}", flush=True)


if __name__ == "__main__":
    main()
