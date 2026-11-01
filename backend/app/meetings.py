from datetime import datetime

from .db import get_session
from .models import Meeting

# Statuses a webhook may still move a meeting out of.
TERMINAL_STATUSES = ("done", "failed", "cancelled")


def _to_dict(m: Meeting) -> dict:
    return {
        "id": str(m.id),
        "user_id": str(m.user_id),
        "platform": m.platform,
        "meeting_url": m.meeting_url,
        "vendor_bot_id": m.vendor_bot_id,
        "status": m.status,
        "title": m.title,
        "scheduled_for": m.scheduled_for,
        "bot_name": m.bot_name,
        "job_id": m.job_id,
        "error_message": m.error_message,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }


def create_meeting(
    user_id: str,
    platform: str,
    meeting_url: str,
    title: str | None,
    scheduled_for: datetime | None = None,
    bot_name: str | None = None,
) -> dict:
    session = get_session()
    try:
        meeting = Meeting(
            user_id=user_id,
            platform=platform,
            meeting_url=meeting_url,
            title=title,
            scheduled_for=scheduled_for,
            bot_name=bot_name,
            status="scheduled" if scheduled_for else "joining",
        )
        session.add(meeting)
        session.commit()
        session.refresh(meeting)
        return _to_dict(meeting)
    finally:
        session.close()


def get_meeting(meeting_id: str) -> dict | None:
    session = get_session()
    try:
        meeting = session.get(Meeting, meeting_id)
        return _to_dict(meeting) if meeting else None
    finally:
        session.close()


def get_meeting_by_bot_id(bot_id: str) -> dict | None:
    session = get_session()
    try:
        meeting = session.query(Meeting).filter_by(vendor_bot_id=bot_id).one_or_none()
        return _to_dict(meeting) if meeting else None
    finally:
        session.close()


def get_meeting_by_job_id(job_id: str) -> dict | None:
    session = get_session()
    try:
        meeting = session.query(Meeting).filter_by(job_id=job_id).first()
        return _to_dict(meeting) if meeting else None
    finally:
        session.close()


def list_meetings_for_user(user_id: str, limit: int = 50) -> list[dict]:
    session = get_session()
    try:
        rows = (
            session.query(Meeting)
            .filter_by(user_id=user_id)
            .order_by(Meeting.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_dict(m) for m in rows]
    finally:
        session.close()


def update_meeting(meeting_id: str, **fields) -> None:
    session = get_session()
    try:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            return
        for key, value in fields.items():
            setattr(meeting, key, value)
        session.commit()
    finally:
        session.close()
