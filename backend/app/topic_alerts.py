"""Topic alert emails: when a public agency meeting is published, everyone
following a topic it covered gets one email listing what was said about their
topics. Same shape as announcements.py's delivery queue -- one TopicNotification
row per (meeting, subscriber), claimed with SKIP LOCKED by a daemon thread in
worker.py, so nobody is emailed twice for a meeting."""

import html
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from . import tokens, users
from .config import settings
from .db import get_session
from .emails import _ACCENT_SOFT, _BG, _BORDER, _LOGO_URL, _NAVY, _TEXT_MUTED
from .mailgun_client import send_email
from .models import (
    AgencyMeeting,
    AgencyMeetingTopic,
    MeetingSource,
    Topic,
    TopicNotification,
    TopicSubscription,
    User,
)

logger = logging.getLogger(__name__)

STALE_CLAIM_SECONDS = 300
MAX_SUBJECT_CHARS = 150


def meeting_url(meeting_id: str, start_ts: float | None = None) -> str:
    url = f"{settings.FRONTEND_URL}/agency-meetings/{meeting_id}"
    return f"{url}?t={int(start_ts)}" if start_ts else url


def unsubscribe_url(user_id: str) -> str:
    return f"{settings.FRONTEND_URL}/unsubscribe?kind=topics&token={tokens.create_topic_unsubscribe_token(user_id)}"


def queue_for_meeting(meeting_id: str) -> int:
    """One pending notification per subscriber of any of the meeting's topics
    who hasn't switched topic alerts off. Safe to run again: existing rows are
    left alone, except a failed one, which goes back to pending (this is how a
    failed send is retried). Returns how many rows were queued or re-queued."""
    mid = uuid.UUID(str(meeting_id))
    session = get_session()
    try:
        meeting = session.get(AgencyMeeting, mid)
        if not meeting or meeting.status != "ready":
            return 0
        user_ids = session.execute(
            select(TopicSubscription.user_id)
            .join(AgencyMeetingTopic, AgencyMeetingTopic.topic_id == TopicSubscription.topic_id)
            .join(User, User.id == TopicSubscription.user_id)
            .where(AgencyMeetingTopic.meeting_id == mid, User.notify_topic_alerts.is_(True))
            .distinct()
        ).scalars().all()
        if not user_ids:
            return 0
        statement = insert(TopicNotification).values([{"meeting_id": mid, "user_id": u} for u in user_ids])
        statement = statement.on_conflict_do_update(
            index_elements=["meeting_id", "user_id"],
            set_={"status": "pending", "claimed_at": None},
            where=(TopicNotification.status == "failed"),
        )
        result = session.execute(statement)
        session.commit()
        return result.rowcount or 0
    finally:
        session.close()


def _matching_topics(session, meeting_id, user_id) -> list[dict]:
    rows = session.execute(
        select(Topic.name, AgencyMeetingTopic.summary, AgencyMeetingTopic.start_ts)
        .join(AgencyMeetingTopic, AgencyMeetingTopic.topic_id == Topic.id)
        .join(TopicSubscription, TopicSubscription.topic_id == Topic.id)
        .where(AgencyMeetingTopic.meeting_id == meeting_id, TopicSubscription.user_id == user_id, Topic.active.is_(True))
        .order_by(AgencyMeetingTopic.start_ts)
    ).all()
    return [{"name": n, "summary": s, "start_ts": t} for n, s, t in rows]


def render_alert(user: dict, meeting: dict, matches: list[dict]) -> tuple[str, str, str, str]:
    """Returns (subject, html, text, unsubscribe_url)."""
    raw_name = user.get("display_name") or user["email"].split("@")[0]
    unsub = unsubscribe_url(user["id"])
    names = ", ".join(m["name"] for m in matches)
    subject = f"New {meeting['agency']} meeting: {names}"[:MAX_SUBJECT_CHARS]
    link = meeting_url(meeting["id"])

    items_html = "".join(
        f"""
                <div style="margin:0 0 18px;">
                  <p style="margin:0 0 4px;font-size:15px;font-weight:700;color:{_NAVY};">{html.escape(m["name"])}</p>
                  <p style="margin:0 0 6px;font-size:14px;line-height:1.55;color:{_NAVY};">{html.escape(m["summary"])}</p>
                  <a href="{html.escape(meeting_url(meeting["id"], m["start_ts"]), quote=True)}"
                     style="font-size:13px;color:{_NAVY};">Jump to this discussion</a>
                </div>"""
        for m in matches
    )
    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:{_BG};font-family:Arial,Helvetica,sans-serif;">
    <span style="display:none;font-size:0;color:{_BG};line-height:0;max-height:0;max-width:0;opacity:0;overflow:hidden;">
      {html.escape(meeting["title"])}
    </span>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:560px;width:100%;background:#ffffff;border:1px solid {_BORDER};border-radius:16px;overflow:hidden;">
            <tr><td style="padding:32px 32px 0;">
              <img src="{_LOGO_URL}" alt="Framewrite" height="22" style="display:block;height:22px;width:auto;" />
            </td></tr>
            <tr><td style="padding:24px 32px 8px;">
              <p style="margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
                        color:{_NAVY};background:{_ACCENT_SOFT};display:inline-block;padding:4px 10px;border-radius:999px;">
                Topic alert
              </p>
              <h1 style="margin:14px 0 8px;font-size:20px;line-height:1.3;color:{_NAVY};">{html.escape(meeting["title"])}</h1>
              <p style="margin:0 0 18px;font-size:13px;color:{_TEXT_MUTED};">{html.escape(meeting["agency"])}</p>
              <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:{_NAVY};">
                Hi {html.escape(raw_name)}, this meeting covered {"a topic" if len(matches) == 1 else "topics"} you follow:
              </p>{items_html}
            </td></tr>
            <tr><td align="center" style="padding:8px 32px 24px;">
              <a href="{html.escape(link, quote=True)}"
                 style="display:inline-block;background:{_NAVY};color:#ffffff;text-decoration:none;font-size:15px;
                        font-weight:600;padding:13px 28px;border-radius:10px;">Read the full summary</a>
            </td></tr>
            <tr><td style="padding:0 32px 24px;border-top:1px solid {_BORDER};">
              <p style="margin:18px 0 0;font-size:12px;color:{_TEXT_MUTED};">
                Summaries are written by AI from the public recording and can contain mistakes.
                The official recording is linked on the meeting page.
              </p>
            </td></tr>
          </table>
          <p style="margin:20px 0 0;font-size:12px;color:{_TEXT_MUTED};">
            You&rsquo;re receiving this because you follow these topics on Framewrite.
            <a href="{html.escape(settings.FRONTEND_URL + "/settings", quote=True)}" style="color:{_TEXT_MUTED};">Manage topics</a> &middot;
            <a href="{html.escape(unsub, quote=True)}" style="color:{_TEXT_MUTED};">Stop topic alerts</a>
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    lines = [f"Hi {raw_name},", "", f"{meeting['agency']}: {meeting['title']}", "", "This meeting covered topics you follow:", ""]
    for m in matches:
        lines += [m["name"], m["summary"], meeting_url(meeting["id"], m["start_ts"]), ""]
    lines += [
        f"Full summary: {link}",
        "",
        "Summaries are written by AI from the public recording and can contain mistakes.",
        "",
        f"Stop topic alerts: {unsub}",
    ]
    return subject, html_body, "\n".join(lines), unsub


def _claim_next(session) -> TopicNotification | None:
    stale = datetime.now(timezone.utc) - timedelta(seconds=STALE_CLAIM_SECONDS)
    row = session.execute(
        select(TopicNotification)
        .where(
            or_(
                TopicNotification.status == "pending",
                and_(TopicNotification.status == "sending", TopicNotification.claimed_at < stale),
            )
        )
        .order_by(TopicNotification.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if row:
        row.status = "sending"
        row.claimed_at = datetime.now(timezone.utc)
        session.commit()
    return row


def send_next_delivery() -> bool:
    """Sends one pending alert. False if there was nothing to send, True
    otherwise (including a failed send, which is recorded -- queue_for_meeting
    puts it back in line). Never raises."""
    session = get_session()
    try:
        row = _claim_next(session)
        if row is None:
            return False
        user = users.get_user_by_id(row.user_id)
        meeting = session.get(AgencyMeeting, row.meeting_id)
        matches = _matching_topics(session, row.meeting_id, row.user_id) if (user and meeting) else []
        if not user or not user["notify_topic_alerts"] or not meeting or meeting.status != "ready" or not matches:
            row.status = "skipped"  # opted out, taken down or unfollowed since it was queued
        else:
            source = session.get(MeetingSource, meeting.source_id)
            card = {"id": str(meeting.id), "title": meeting.title, "agency": source.agency_name if source else ""}
            try:
                subject, html_body, text, unsub = render_alert(user, card, matches)
                ok = send_email(user["email"], subject, text, html=html_body, headers={"List-Unsubscribe": f"<{unsub}>"})
            except Exception:
                logger.exception("Topic alert to %s crashed", user["email"])
                ok = False
            row.status = "sent" if ok else "failed"
            row.sent_at = datetime.now(timezone.utc) if ok else None
        session.commit()
        return True
    except Exception:
        logger.exception("Topic alert delivery error")
        session.rollback()
        return False
    finally:
        session.close()


def run_delivery_loop() -> None:
    """Blocking loop for a daemon thread in worker.py."""
    while True:
        if send_next_delivery():
            time.sleep(settings.ANNOUNCEMENT_SEND_DELAY_SECONDS)
        else:
            time.sleep(settings.WORKER_POLL_SECONDS)
