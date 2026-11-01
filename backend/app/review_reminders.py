"""Reminder emails for jobs paused for the user's review (frames, scenes or
research topics). The first "needs your review" email goes out when the job
pauses (emails.notify_review_needed); this sends one more if it's still
waiting REVIEW_REMINDER_AFTER_HOURS later. Runs as a daemon thread in
worker.py, like the announcement delivery loop."""

import logging
import time
from datetime import datetime, timedelta, timezone

from . import emails, jobs
from .config import settings

logger = logging.getLogger(__name__)


def send_due_reminders() -> int:
    waiting_since = datetime.now(timezone.utc) - timedelta(hours=settings.REVIEW_REMINDER_AFTER_HOURS)
    sent = 0
    for job_id in jobs.claim_review_reminders(waiting_since):
        # The claim stamped review_reminder_sent_at (which the admin activity
        # feed shows as "reminder sent") -- take it back if no email went out.
        if emails.notify_review_reminder(job_id):
            sent += 1
        else:
            jobs.release_review_reminder(job_id)
    return sent


def run_loop() -> None:
    """Blocking loop for a daemon thread -- its own thread because the main
    worker loop blocks for a job's full processing time."""
    while True:
        try:
            sent = send_due_reminders()
            if sent:
                logger.info("Sent %d review reminder(s)", sent)
        except Exception:
            # A DB blip must not kill the thread, or reminders stop silently.
            logger.exception("Review reminder sweep failed")
        time.sleep(settings.REVIEW_REMINDER_CHECK_SECONDS)
