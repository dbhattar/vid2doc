"""The public showcase's merged feed: approved user documents (jobs) plus
ready, un-hidden public agency meetings (see topics.py/agency_ingest.py),
ordered and paginated as one list. Only ids are merged in SQL; each page is
then hydrated from the two sources, so the list query stays cheap.
"""

from sqlalchemy import String, cast, func, literal, select, union_all

from .db import get_session
from .models import AgencyMeeting, AgencyMeetingTopic, Job, MeetingSource, Topic


def _entries():
    """(id, kind, featured_at) for everything the showcase can show."""
    documents = select(
        cast(Job.id, String).label("id"),
        literal("document").label("kind"),
        Job.public_reviewed_at.label("featured_at"),
    ).where(Job.public_status == "approved", Job.public_hidden.is_(False))
    meetings = select(
        cast(AgencyMeeting.id, String).label("id"),
        literal("meeting").label("kind"),
        func.coalesce(AgencyMeeting.processed_at, AgencyMeeting.created_at).label("featured_at"),
    ).where(AgencyMeeting.status == "ready")
    return union_all(documents, meetings).subquery()


def page_entries(limit: int, offset: int, random: bool) -> tuple[list[tuple[str, str]], int]:
    """([(id, kind), ...] for one page, total). `random` returns a random
    sample instead of the newest-first page (the homepage's few items)."""
    session = get_session()
    try:
        entries = _entries()
        total = session.execute(select(func.count()).select_from(entries)).scalar_one()
        order = func.random() if random else entries.c.featured_at.desc().nulls_last()
        rows = session.execute(
            select(entries.c.id, entries.c.kind)
            .order_by(order, entries.c.id)
            .limit(limit)
            .offset(0 if random else offset)
        ).all()
        return [(r.id, r.kind) for r in rows], total
    finally:
        session.close()


def meeting_items(meeting_ids: list[str]) -> dict[str, dict]:
    """Showcase card/detail payloads for ready meetings, by id. A meeting that
    stopped being public since the page's ids were chosen is simply absent."""
    if not meeting_ids:
        return {}
    session = get_session()
    try:
        rows = session.execute(
            select(AgencyMeeting, MeetingSource.agency_name)
            .join(MeetingSource, MeetingSource.id == AgencyMeeting.source_id)
            .where(AgencyMeeting.id.in_(meeting_ids), AgencyMeeting.status == "ready")
        ).all()
        topic_rows = session.execute(
            select(AgencyMeetingTopic.meeting_id, Topic.slug, Topic.name)
            .join(Topic, Topic.id == AgencyMeetingTopic.topic_id)
            .where(AgencyMeetingTopic.meeting_id.in_([m.id for m, _ in rows]), Topic.active.is_(True))
            .order_by(AgencyMeetingTopic.start_ts)
        ).all()
        topics: dict[str, list[dict]] = {}
        for meeting_id, slug, name in topic_rows:
            topics.setdefault(str(meeting_id), []).append({"slug": slug, "name": name})
        return {
            str(m.id): {
                "id": str(m.id),
                "kind": "meeting",
                "title": m.title,
                "agency": agency,
                "meeting_date": m.meeting_date,
                "duration_seconds": m.duration_seconds,
                "featured_since": m.processed_at or m.created_at,
                "summary": m.summary,
                "topics": topics.get(str(m.id), []),
            }
            for m, agency in rows
        }
    finally:
        session.close()
