"""Admin-composed announcement emails ("new feature", "product update") to
every user who hasn't unsubscribed. Unlike emails.py's job/welcome emails
these are marketing-ish, so every message carries an unsubscribe link (and a
List-Unsubscribe header) backed by User.announcements_opt_out -- see
routes/announcements.py for the public unsubscribe endpoint and
routes/admin.py for the admin-side send."""

import html
import logging

from . import tokens, users
from .config import settings
from .emails import _job_status_email_shell
from .mailgun_client import send_email

logger = logging.getLogger(__name__)

MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 10_000

_TEXT_MUTED = "#5b6b83"


def unsubscribe_url(user_id: str) -> str:
    return f"{settings.FRONTEND_URL}/unsubscribe?token={tokens.create_unsubscribe_token(user_id)}"


def _body_html(body: str) -> str:
    """Plain text in, minimal HTML out: blank-line-separated paragraphs, single
    newlines kept as <br>. Escaped, so an admin can't accidentally (or a
    compromised admin account deliberately) inject markup/scripts."""
    paragraphs = [p.strip() for p in body.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return "\n".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:{_TEXT_MUTED};">'
        f"{html.escape(p).replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )


def send_announcement_to_user(user: dict, subject: str, body: str) -> bool:
    unsub = unsubscribe_url(user["id"])
    html_body = _job_status_email_shell(
        "Update",
        html.escape(subject),
        _body_html(body),
        "Open Framewrite",
        f"{settings.FRONTEND_URL}/dashboard",
        f'You\'re getting this because you have a Framewrite account. <a href="{unsub}" style="color:{_TEXT_MUTED};">Unsubscribe</a>',
    )
    text = f"{body}\n\n-- The Framewrite team\n\nUnsubscribe: {unsub}"
    return send_email(
        user["email"], subject, text, html=html_body, headers={"List-Unsubscribe": f"<{unsub}>"}
    )


def send_announcement(subject: str, body: str) -> tuple[int, int]:
    """Sends to every non-unsubscribed user, one message each (so each gets
    their own unsubscribe link). Returns (sent, failed). Never raises -- meant
    to run as a background task, where an exception would just vanish."""
    sent = failed = 0
    try:
        for user in users.list_announcement_recipients():
            try:
                ok = send_announcement_to_user(user, subject, body)
            except Exception:
                logger.exception("Announcement email to %s crashed", user["email"])
                ok = False
            sent += ok
            failed += not ok
    except Exception:
        logger.exception("Announcement send aborted")
    logger.info("Announcement %r finished: %d sent, %d failed", subject, sent, failed)
    return sent, failed
