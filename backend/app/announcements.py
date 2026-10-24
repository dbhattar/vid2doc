"""Admin-composed announcement emails ("new feature", "product update") to
the selected users (or everyone) who haven't unsubscribed. Sent one email per
user by the worker, with a delay between each. Unlike emails.py's job/welcome emails
these are marketing-ish, so every message carries an unsubscribe link (and a
List-Unsubscribe header) backed by User.announcements_opt_out -- see
routes/announcements.py for the public unsubscribe endpoint and
routes/admin.py for the admin-side send."""

import html
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from . import tokens, users
from .config import settings
from .db import get_session
from .models import Announcement, AnnouncementDelivery
from .emails import _ACCENT_SOFT, _BG, _BORDER, _LOGO_URL, _NAVY, _TEXT_MUTED
from .mailgun_client import send_email

logger = logging.getLogger(__name__)

MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 10_000

TAGS = ("Update", "New feature", "Announcement")
DEFAULT_TAG = TAGS[0]
DEFAULT_CTA_LABEL = "Open Framewrite"


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


def validate_cta(cta_label: str | None, cta_url: str | None) -> tuple[str, str]:
    """Falls back to the dashboard. The URL is admin-supplied and goes into an
    href, so only http(s) is allowed (no javascript: etc.)."""
    label = (cta_label or "").strip() or DEFAULT_CTA_LABEL
    url = (cta_url or "").strip() or f"{settings.FRONTEND_URL}/dashboard"
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Button link must start with http:// or https://")
    return label, url


def render_announcement(
    user: dict,
    subject: str,
    body: str,
    tag: str = DEFAULT_TAG,
    cta_label: str | None = None,
    cta_url: str | None = None,
) -> tuple[str, str, str]:
    """Returns (html, text, unsubscribe_url) -- same card layout as
    emails.send_welcome_email (logo, tag pill, heading, navy button, unsubscribe
    line under the card), with the admin's subject/body in the middle."""
    tag = tag if tag in TAGS else DEFAULT_TAG
    cta_label, cta_url = validate_cta(cta_label, cta_url)
    raw_name = user.get("display_name") or user["email"].split("@")[0]
    unsub = unsubscribe_url(user["id"])
    preheader = " ".join(body.split())[:140]

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:{_BG};font-family:Arial,Helvetica,sans-serif;">
    <span style="display:none;font-size:0;color:{_BG};line-height:0;max-height:0;max-width:0;opacity:0;overflow:hidden;">
      {html.escape(preheader)}
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
                  {html.escape(tag)}
                </p>
                <h1 style="margin:14px 0 12px;font-size:22px;line-height:1.3;letter-spacing:-0.01em;color:{_NAVY};">
                  {html.escape(subject)}
                </h1>
                <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:{_NAVY};">
                  Hi {html.escape(raw_name)},
                </p>
                {_body_html(body)}
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:8px 32px 28px;">
                <a href="{html.escape(cta_url, quote=True)}"
                   style="display:inline-block;background:{_NAVY};color:#ffffff;text-decoration:none;
                          font-size:15px;font-weight:600;padding:13px 28px;border-radius:10px;">
                  {html.escape(cta_label)}
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
            You&rsquo;re receiving this because you have a Framewrite account.
            <a href="{html.escape(unsub, quote=True)}" style="color:{_TEXT_MUTED};">Unsubscribe</a>
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    text = (
        f"Hi {raw_name},\n\n{body}\n\n{cta_label}: {cta_url}\n\n-- The Framewrite team\n\n"
        f"Unsubscribe: {unsub}"
    )
    return html_body, text, unsub


def send_announcement_to_user(
    user: dict,
    subject: str,
    body: str,
    tag: str = DEFAULT_TAG,
    cta_label: str | None = None,
    cta_url: str | None = None,
) -> bool:
    html_body, text, unsub = render_announcement(user, subject, body, tag, cta_label, cta_url)
    return send_email(
        user["email"], subject, text, html=html_body, headers={"List-Unsubscribe": f"<{unsub}>"}
    )


STALE_CLAIM_SECONDS = 300


def queue_announcement(
    subject: str,
    body: str,
    created_by: str,
    user_ids: list[str] | None,
    tag: str = DEFAULT_TAG,
    cta_label: str | None = None,
    cta_url: str | None = None,
) -> tuple[str, int]:
    """Creates the announcement and one pending delivery per recipient --
    nothing is sent here, the worker does that (see send_next_delivery).
    user_ids=None means every non-unsubscribed user; otherwise just those
    users, still minus anyone who has unsubscribed. Returns
    (announcement_id, recipient_count)."""
    recipients = users.list_announcement_recipients()
    if user_ids is not None:
        wanted = set(user_ids)
        recipients = [u for u in recipients if u["id"] in wanted]
    session = get_session()
    try:
        announcement = Announcement(
            subject=subject, body=body, created_by=created_by, tag=tag, cta_label=cta_label, cta_url=cta_url
        )
        session.add(announcement)
        session.flush()
        session.add_all(
            AnnouncementDelivery(announcement_id=announcement.id, user_id=u["id"], status="pending")
            for u in recipients
        )
        session.commit()
        return str(announcement.id), len(recipients)
    finally:
        session.close()


def _claim_next_delivery(session) -> AnnouncementDelivery | None:
    # SKIP LOCKED so several workers never pick the same delivery. A
    # delivery stuck in "sending" (worker died mid-send) is picked up again
    # after STALE_CLAIM_SECONDS -- at-least-once, so a crash can rarely
    # produce a duplicate email, never a silently dropped one.
    stale = datetime.now(timezone.utc) - timedelta(seconds=STALE_CLAIM_SECONDS)
    delivery = session.execute(
        select(AnnouncementDelivery)
        .where(
            or_(
                AnnouncementDelivery.status == "pending",
                and_(AnnouncementDelivery.status == "sending", AnnouncementDelivery.claimed_at < stale),
            )
        )
        .order_by(AnnouncementDelivery.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if delivery:
        delivery.status = "sending"
        delivery.claimed_at = datetime.now(timezone.utc)
        session.commit()
    return delivery


def send_next_delivery() -> bool:
    """Sends one pending announcement email. Returns False if there was
    nothing to send (the worker then idles), True otherwise -- including on a
    failed send, which is recorded and not retried (retrying a bounced
    address forever helps no one). Never raises."""
    session = get_session()
    try:
        delivery = _claim_next_delivery(session)
        if delivery is None:
            return False
        announcement = session.get(Announcement, delivery.announcement_id)
        user = users.get_user_by_id(delivery.user_id)
        if not user or user["announcements_opt_out"]:
            delivery.status = "skipped"
        else:
            try:
                ok = send_announcement_to_user(
                    user,
                    announcement.subject,
                    announcement.body,
                    announcement.tag,
                    announcement.cta_label,
                    announcement.cta_url,
                )
            except Exception:
                logger.exception("Announcement email to %s crashed", user["email"])
                ok = False
            delivery.status = "sent" if ok else "failed"
            delivery.sent_at = datetime.now(timezone.utc) if ok else None
        session.commit()
        return True
    except Exception:
        logger.exception("Announcement delivery loop error")
        session.rollback()
        return False
    finally:
        session.close()


def run_delivery_loop() -> None:
    """Blocking loop for a daemon thread in worker.py -- its own thread
    because the main worker loop blocks for a video's full processing time,
    which would stall the emails behind it."""
    while True:
        if send_next_delivery():
            time.sleep(settings.ANNOUNCEMENT_SEND_DELAY_SECONDS)
        else:
            time.sleep(settings.WORKER_POLL_SECONDS)


def list_recent_announcements(limit: int = 20) -> list[dict]:
    session = get_session()
    try:
        rows = session.query(Announcement).order_by(Announcement.created_at.desc()).limit(limit).all()
        counts: dict = {}
        for announcement_id, status, n in (
            session.query(AnnouncementDelivery.announcement_id, AnnouncementDelivery.status, func.count())
            .filter(AnnouncementDelivery.announcement_id.in_([a.id for a in rows]))
            .group_by(AnnouncementDelivery.announcement_id, AnnouncementDelivery.status)
            .all()
        ):
            counts.setdefault(announcement_id, {})[status] = n
        return [
            {
                "id": str(a.id),
                "subject": a.subject,
                "created_at": a.created_at,
                "counts": {
                    s: counts.get(a.id, {}).get(s, 0) for s in ("pending", "sending", "sent", "failed", "skipped")
                },
            }
            for a in rows
        ]
    finally:
        session.close()
