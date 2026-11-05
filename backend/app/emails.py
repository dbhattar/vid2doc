import html
import logging

from .config import settings
from .mailgun_client import send_email

logger = logging.getLogger(__name__)

_DASHBOARD_URL = "https://app.framewrite.cc/dashboard"
_LOGO_URL = "https://framewrite.cc/images/framewrite_logo.png"

# Brand tokens, matching styles.css's :root (navy/accent/bg) so transactional
# email feels like the same product as the marketing site and app.
_NAVY = "#1c2b4a"
_ACCENT = "#e2962f"
_ACCENT_SOFT = "#fbe9cf"
_BG = "#faf9f6"
_BORDER = "#e7e3d9"
_TEXT_MUTED = "#5b6b83"

_STEPS = [
    ("1", "Upload", "Drop in a video or audio file -- no editing, no timestamps to hunt down first."),
    ("2", "We do the work", "Transcript, speaker labels, and the right slides/diagrams pulled out automatically."),
    ("3", "Search it", "Get back a clean document you can search in seconds, instead of rewatching the video."),
]


def _step_row(number: str, title: str, body: str) -> str:
    return f"""
      <tr>
        <td width="36" valign="top" style="padding:0 12px 20px 0;">
          <div style="width:24px;height:24px;border-radius:999px;background:{_ACCENT_SOFT};color:{_NAVY};
                      border:1px solid {_ACCENT};font-family:Arial,Helvetica,sans-serif;font-size:12px;
                      font-weight:700;line-height:22px;text-align:center;">{number}</div>
        </td>
        <td valign="top" style="padding:0 0 20px 0;font-family:Arial,Helvetica,sans-serif;">
          <p style="margin:0 0 2px;font-size:14px;font-weight:700;color:{_NAVY};">{title}</p>
          <p style="margin:0;font-size:14px;color:{_TEXT_MUTED};line-height:1.5;">{body}</p>
        </td>
      </tr>"""


def send_welcome_email(user: dict) -> None:
    raw_name = user.get("display_name") or user["email"].split("@")[0]
    name = html.escape(raw_name)
    subject = "Welcome to Framewrite"

    steps_html = "".join(_step_row(number, title, body) for number, title, body in _STEPS)

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:{_BG};font-family:Arial,Helvetica,sans-serif;">
    <span style="display:none;font-size:0;color:{_BG};line-height:0;max-height:0;max-width:0;opacity:0;overflow:hidden;">
      Upload your first video and see Framewrite turn it into a searchable document.
    </span>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:560px;width:100%;background:#ffffff;border:1px solid {_BORDER};
                        border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 0;">
                <img src="{_LOGO_URL}" alt="Framewrite" height="22" style="display:block;height:22px;width:auto;" />
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px;">
                <p style="margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
                          color:{_NAVY};background:{_ACCENT_SOFT};display:inline-block;padding:4px 10px;border-radius:999px;">
                  Now live
                </p>
                <h1 style="margin:14px 0 8px;font-size:22px;line-height:1.3;letter-spacing:-0.01em;color:{_NAVY};">
                  Welcome to Framewrite, {name}
                </h1>
                <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  Turn any video into a document you'll actually use -- full transcript, speaker labels,
                  and the right images dropped in at the right spot.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  {steps_html}
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:4px 32px 28px;">
                <a href="{_DASHBOARD_URL}"
                   style="display:inline-block;background:{_NAVY};color:#ffffff;text-decoration:none;
                          font-size:15px;font-weight:600;padding:13px 28px;border-radius:10px;">
                  Upload your first video
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 28px;border-top:1px solid {_BORDER};">
                <p style="margin:20px 0 0;font-size:13px;color:{_TEXT_MUTED};">
                  Pay-as-you-go, no subscription -- $1/hour of video, $0.40/hour of audio.
                </p>
              </td>
            </tr>
          </table>
          <p style="margin:20px 0 0;font-size:12px;color:{_TEXT_MUTED};">
            You're receiving this because you just signed up for Framewrite.
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    text = (
        f"Welcome to Framewrite, {raw_name}!\n\n"
        "Turn any video into a document you'll actually use -- full transcript, speaker labels, "
        "and the right images dropped in at the right spot.\n\n"
        "How it works:\n"
        "1. Upload -- drop in a video or audio file, no editing needed.\n"
        "2. We do the work -- transcript, speaker labels, and the right slides/diagrams pulled out automatically.\n"
        "3. Search it -- get back a clean document you can search in seconds.\n\n"
        f"Upload your first video: {_DASHBOARD_URL}\n\n"
        "Pay-as-you-go, no subscription: $1/hour of video, $0.40/hour of audio.\n\n"
        "-- The Framewrite team"
    )

    send_email(user["email"], subject, text, html=html_body)


def _job_status_email_shell(eyebrow: str, heading: str, body_html: str, cta_label: str, cta_url: str, footer: str) -> str:
    """Shared table/brand-token shell for send_job_done_email/send_job_failed_email
    -- same structure as send_welcome_email's markup, just without the numbered
    steps table (not relevant once a job has already finished)."""
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:{_BG};font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:560px;width:100%;background:#ffffff;border:1px solid {_BORDER};
                        border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 0;">
                <img src="{_LOGO_URL}" alt="Framewrite" height="22" style="display:block;height:22px;width:auto;" />
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px;">
                <p style="margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
                          color:{_NAVY};background:{_ACCENT_SOFT};display:inline-block;padding:4px 10px;border-radius:999px;">
                  {eyebrow}
                </p>
                <h1 style="margin:14px 0 8px;font-size:22px;line-height:1.3;letter-spacing:-0.01em;color:{_NAVY};">
                  {heading}
                </h1>
                {body_html}
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:4px 32px 28px;">
                <a href="{cta_url}"
                   style="display:inline-block;background:{_NAVY};color:#ffffff;text-decoration:none;
                          font-size:15px;font-weight:600;padding:13px 28px;border-radius:10px;">
                  {cta_label}
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 28px;border-top:1px solid {_BORDER};">
                <p style="margin:20px 0 0;font-size:13px;color:{_TEXT_MUTED};">
                  {footer}
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def send_job_done_email(user: dict, job: dict) -> None:
    raw_name = user.get("display_name") or user["email"].split("@")[0]
    name = html.escape(raw_name)
    raw_title = job.get("title") or "Your document"
    title = html.escape(raw_title)
    job_url = f"{settings.FRONTEND_URL}/dashboard/jobs/{job['id']}"
    subject = f'"{raw_title}" is ready'

    body_html = f"""\
                <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  Hi {name}, your document &ldquo;{title}&rdquo; is done processing and ready to view.
                </p>"""
    html_body = _job_status_email_shell(
        "Done", f"&ldquo;{title}&rdquo; is ready", body_html, "View your document", job_url,
        "Pay-as-you-go, no subscription -- $1/hour of video, $0.40/hour of audio.",
    )
    text = (
        f"Hi {raw_name},\n\nYour document \"{raw_title}\" is ready.\n\n"
        f"View it: {job_url}\n\n-- The Framewrite team"
    )
    send_email(user["email"], subject, text, html=html_body)


def send_job_failed_email(user: dict, job: dict) -> None:
    raw_name = user.get("display_name") or user["email"].split("@")[0]
    name = html.escape(raw_name)
    raw_title = job.get("title") or "Your document"
    title = html.escape(raw_title)
    job_url = f"{settings.FRONTEND_URL}/dashboard/jobs/{job['id']}"
    subject = f'"{raw_title}" failed to process'

    error_line = ""
    if job.get("error_message"):
        error_line = f"""<p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:{_TEXT_MUTED};">{html.escape(job["error_message"])}</p>"""
    body_html = f"""\
                <p style="margin:0 0 12px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  Hi {name}, your job &ldquo;{title}&rdquo; failed to process. You've been refunded if you were charged.
                </p>
                {error_line}"""
    html_body = _job_status_email_shell(
        "Failed", f"&ldquo;{title}&rdquo; couldn't be processed", body_html, "View details", job_url,
        "If this keeps happening, reply to this email and we'll take a look.",
    )
    error_suffix = f": {job['error_message']}" if job.get("error_message") else "."
    text = (
        f"Hi {raw_name},\n\nYour job \"{raw_title}\" failed to process{error_suffix}\n\n"
        f"You've been refunded if you were charged. Details: {job_url}\n\n-- The Framewrite team"
    )
    send_email(user["email"], subject, text, html=html_body)


def send_review_needed_email(user: dict, job: dict, reminder: bool = False) -> bool:
    raw_name = user.get("display_name") or user["email"].split("@")[0]
    name = html.escape(raw_name)
    raw_title = job.get("title") or "Your job"
    title = html.escape(raw_title)
    job_url = f"{settings.FRONTEND_URL}/dashboard/jobs/{job['id']}"

    if job.get("progress_stage") == "awaiting_topic_review":
        what, cta, action = "topics", "Review topics", "confirm which topics to research"
        detail = "Research only starts once you've confirmed the topics -- you can edit or remove them, or add your own."
    elif job.get("job_type") == "video_gen":
        what, cta, action = "scenes", "Review scenes", "review the scenes"
        detail = "Rendering only starts once you've checked the scenes and swapped in any better footage."
    else:
        what, cta, action = "frames", "Review frames", "choose which frames go in the document"
        detail = "Your document is written once you've picked which slides, diagrams and tables to keep."

    if reminder:
        subject = f'Reminder: "{raw_title}" is still waiting for your review'
        eyebrow, heading = "Reminder", f"Your {what} are still waiting"
        intro = f"&ldquo;{title}&rdquo; has been paused for a day, waiting for you to {action}."
        text_intro = f"\"{raw_title}\" has been paused for a day, waiting for you to {action}."
    else:
        subject = f'"{raw_title}" needs your review'
        eyebrow, heading = "Needs your review", f"Your {what} are ready to review"
        intro = f"&ldquo;{title}&rdquo; is paused and waiting for you to {action}."
        text_intro = f"\"{raw_title}\" is paused and waiting for you to {action}."
    body_html = f"""\
                <p style="margin:0 0 12px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  Hi {name}, {intro}
                </p>
                <p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:{_TEXT_MUTED};">{detail}</p>"""
    html_body = _job_status_email_shell(
        eyebrow, heading, body_html, cta, job_url,
        "Jobs waiting for review are removed after the retention period, so don't leave it too long.",
    )
    text = (
        f"Hi {raw_name},\n\n{text_intro}\n"
        f"{detail}\n\nReview it: {job_url}\n\n-- The Framewrite team"
    )
    return send_email(user["email"], subject, text, html=html_body)


def notify_review_needed(job_id: str) -> None:
    """Best-effort "this job is waiting on you" email -- same contract as
    notify_job_status_change (skips anonymous jobs, swallows every
    exception so a broken mail provider can't fail the job). Call right
    after the jobs.update_job(...) that sets status="awaiting_review"."""
    from . import jobs, users

    try:
        job = jobs.get_job(job_id)
        if not job or not job.get("user_id") or job["status"] != "awaiting_review":
            return
        user = users.get_user_by_id(job["user_id"])
        if not user or not user.get("email"):
            return
        send_review_needed_email(user, job)
    except Exception:
        logger.exception("Failed to send review-needed email for job %s", job_id)


def notify_review_reminder(job_id: str) -> bool:
    """Best-effort reminder for a job that has sat in awaiting_review for a
    day (see review_reminders.py). Same contract as notify_review_needed --
    never raises, skips a job that's no longer waiting -- but returns whether
    an email actually went out, so the caller only records a reminder that
    was really sent."""
    from . import jobs, users

    try:
        job = jobs.get_job(job_id)
        if not job or not job.get("user_id") or job["status"] != "awaiting_review":
            return False
        user = users.get_user_by_id(job["user_id"])
        if not user or not user.get("email"):
            return False
        return send_review_needed_email(user, job, reminder=True)
    except Exception:
        logger.exception("Failed to send review reminder email for job %s", job_id)
        return False


def notify_meeting_issue(meeting_id: str, kind: str, detail: str | None = None) -> None:
    """Best-effort email for a meeting that can't become a document on its
    own: kind "payment" (wallet too low when the meeting ended -- detail is
    the cost) or "failed" (detail is a user-safe reason). Same contract as
    the other notify_* functions: never raises."""
    from . import meetings, users

    try:
        meeting = meetings.get_meeting(meeting_id)
        if not meeting:
            return
        user = users.get_user_by_id(meeting["user_id"])
        if not user or not user.get("email"):
            return
        raw_name = user.get("display_name") or user["email"].split("@")[0]
        name = html.escape(raw_name)
        raw_title = meeting.get("title") or "Your meeting"
        title = html.escape(raw_title)
        if kind == "payment":
            subject = f'Add funds to get the notes for "{raw_title}"'
            eyebrow, heading, cta = "Action needed", "Your meeting notes are waiting", "Add funds"
            cta_url = f"{settings.FRONTEND_URL}/settings/billing"
            message = (
                f"The notetaker captured &ldquo;{title}&rdquo;, but your wallet was too low to process it "
                f"({html.escape(detail or '')} needed). Add funds, then open Meetings and choose Process."
            )
            text_message = (
                f"The notetaker captured \"{raw_title}\", but your wallet was too low to process it "
                f"({detail} needed). Add funds, then open Meetings and choose Process."
            )
        else:
            subject = f'The notetaker couldn\'t record "{raw_title}"'
            eyebrow, heading, cta = "Failed", "We couldn't record that meeting", "View meetings"
            cta_url = f"{settings.FRONTEND_URL}/meetings"
            message = f"{html.escape(detail or 'Something went wrong.')} You haven't been charged."
            text_message = f"{detail or 'Something went wrong.'} You haven't been charged."
        body_html = f"""\
                <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  Hi {name}, {message}
                </p>"""
        html_body = _job_status_email_shell(eyebrow, heading, body_html, cta, cta_url, "Pay-as-you-go, no subscription.")
        text = f"Hi {raw_name},\n\n{text_message}\n\n{cta_url}\n\n-- The Framewrite team"
        send_email(user["email"], subject, text, html=html_body)
    except Exception:
        logger.exception("Failed to send meeting-issue email for meeting %s", meeting_id)


def notify_feature_request(request_id: str) -> None:
    """Best-effort email to every admin (ADMIN_EMAILS) that someone asked for
    a gated feature. Never raises."""
    from . import feature_requests, users

    try:
        request = feature_requests.get_request(request_id)
        user = users.get_user_by_id(request["user_id"]) if request else None
        if not request or not user or not settings.ADMIN_EMAILS:
            return
        who = user.get("display_name") or user["email"]
        note = request.get("message") or ""
        admin_url = f"{settings.FRONTEND_URL}/admin"
        body_html = f"""\
                <p style="margin:0 0 12px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  {html.escape(who)} ({html.escape(user["email"])}) asked for access to the Meetings preview.
                </p>
                {f'<p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:{_TEXT_MUTED};">&ldquo;{html.escape(note)}&rdquo;</p>' if note else ""}"""
        html_body = _job_status_email_shell(
            "Access request", "Someone requested Meetings access", body_html, "Review requests", admin_url,
            "Approve or decline it from the admin dashboard.",
        )
        text = f"{who} ({user['email']}) asked for access to the Meetings preview.\n{note}\n\n{admin_url}"
        for admin_email in sorted(settings.ADMIN_EMAILS):
            send_email(admin_email, f"Meetings access request from {who}", text, html=html_body)
    except Exception:
        logger.exception("Failed to send feature-request email for %s", request_id)


def notify_feature_approved(user_id: str) -> None:
    """Best-effort email telling a user their Meetings access is on."""
    from . import users

    try:
        user = users.get_user_by_id(user_id)
        if not user or not user.get("email"):
            return
        raw_name = user.get("display_name") or user["email"].split("@")[0]
        cta_url = f"{settings.FRONTEND_URL}/meetings"
        body_html = f"""\
                <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">
                  Hi {html.escape(raw_name)}, your Meetings preview access is on. Paste a Zoom, Google Meet or
                  Teams link and the notetaker will join, record, and email you the notes when it ends.
                </p>"""
        html_body = _job_status_email_shell(
            "Preview access", "Meetings is ready for you", body_html, "Open Meetings", cta_url,
            "Meetings is a preview and may have rough edges -- tell us what you think.",
        )
        text = (
            f"Hi {raw_name},\n\nYour Meetings preview access is on. Paste a Zoom, Google Meet or Teams link "
            f"and the notetaker will join, record, and email you the notes.\n\n{cta_url}\n\n-- The Framewrite team"
        )
        send_email(user["email"], "Your Meetings preview access is on", text, html=html_body)
    except Exception:
        logger.exception("Failed to send feature-approved email for user %s", user_id)


def notify_job_status_change(job_id: str) -> None:
    """Best-effort job-completion/failure email -- skips anonymous jobs
    (user_id IS NULL; nothing creates these anymore since the trial-upload
    feature was removed, but old rows may still exist), and swallows every exception: a
    broken/misconfigured mail provider must never fail, retry, or roll back
    the job whose status transition triggered this. Call this immediately
    after the jobs.update_job(...) call that actually flips status to
    "done"/"failed" -- see pipeline.py's _finalize_document and run_job's
    except block, and retention.py's stale-review sweep."""
    from . import jobs, meetings, users  # local import: avoids a module-load-order
                                          # dependency between emails.py and jobs.py/users.py

    try:
        job = jobs.get_job(job_id)
        if not job or not job.get("user_id") or job["status"] not in ("done", "failed"):
            return
        user = users.get_user_by_id(job["user_id"])
        if not user or not user.get("email"):
            return
        # Only the "ready" email is optional (failures always send). A
        # meeting's notes follow that meeting's own choice, whose default
        # comes from Settings; any other job follows the account-wide one.
        if job["status"] == "done":
            meeting = meetings.get_meeting_by_job_id(job_id)
            wanted = meeting["notify_when_ready"] if meeting else user["notify_job_done"]
            if not wanted:
                return
            send_job_done_email(user, job)
        else:
            send_job_failed_email(user, job)
    except Exception:
        logger.exception("Failed to send job-status email for job %s", job_id)
