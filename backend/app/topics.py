"""Topics for public agency meetings: the admin-curated topic list, tagging a
finished meeting against it with the LLM, and the queries the public pages and
subscriptions use. See agency_ingest.py for how a meeting gets here.

The topic list grows by itself: a subject the model sees that isn't on it
becomes a new active Topic (people can follow it at once), unless
TOPICS_AUTO_CREATE is off, in which case it becomes a TopicSuggestion for an
admin to approve. Either way an admin can deactivate a topic -- a deactivated
topic is never recreated or attached again -- and a brand-new topic has no
followers, so a one-off label can't notify anyone.
"""

import logging
import re
import uuid

from sqlalchemy import func, select

from .config import settings
from .db import get_session
from .models import AgencyMeeting, AgencyMeetingTopic, Topic, TopicSubscription, TopicSuggestion
from .stages import transform

logger = logging.getLogger(__name__)

# Roughly 8k tokens of transcript per LLM call.
CHUNK_CHARS = 30_000
MAX_TOPIC_SUMMARY_CHARS = 600
MAX_NAME_CHARS = 80

TOPIC_SYSTEM_PROMPT = """You are tagging part of a public government meeting transcript with topics, so people who follow a topic can be told when a meeting discussed it.

You get a TOPIC LIST and a stretch of transcript lines like "[123s] Jane Doe: ...". Rules:
- Report a topic only if it was actually discussed in this stretch -- a substantive agenda item or sustained discussion, not a passing mention.
- Use the EXACT name from the TOPIC LIST whenever one fits. Only if a substantial subject fits nothing on the list, report it with a short new name (2-4 words, title case).
- summary: one or two plain sentences on what was said or decided about the topic here. No speculation, nothing the transcript doesn't support.
- start_ts and end_ts: the seconds (from the [123s] markers) where the discussion of the topic begins and ends in this stretch.
- chunk_summary: two or three sentences covering everything of substance in this stretch.
- Return an empty topics list if nothing substantive was discussed (roll call, recess, procedure only)."""

TOPIC_SCHEMA = transform._object(
    {
        "chunk_summary": transform.STRING,
        "topics": transform._array(
            transform._object(
                {
                    "topic": transform.STRING,
                    "summary": transform.STRING,
                    "start_ts": {"type": "number"},
                    "end_ts": {"type": "number"},
                }
            )
        ),
    }
)

SUMMARY_SYSTEM_PROMPT = """You are writing the overview of a public government meeting from notes on each part of it. Write one short paragraph (3-5 sentences) saying what the meeting covered and any decisions or votes mentioned. Use only what the notes say. Plain text, no headings or bullets."""

SUMMARY_SCHEMA = transform._object({"summary": transform.STRING})


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _clean_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not name or len(name) > MAX_NAME_CHARS or not name.isprintable():
        return ""
    return name


# --- LLM tagging ------------------------------------------------------------


def _chunks(segments: list[dict], speaker_names: dict) -> list[str]:
    chunks, current, size = [], [], 0
    for s in segments:
        speaker = speaker_names.get(s.get("speaker"), s.get("speaker") or "Speaker")
        line = f"[{float(s.get('start_ts', 0)):.0f}s] {speaker}: {s.get('text', '')}"
        if current and size + len(line) > CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def analyze(title: str, segments: list[dict], speaker_names: dict, topic_names: list[str], duration: float | None) -> dict:
    """{"summary": str, "topics": [{"topic": <listed name or None>, "name",
    "summary", "start_ts", "end_ts"}]} -- "topic" is the matched list entry's
    name, None for a subject that isn't on the list. Raises whatever the LLM
    call raises; the caller decides what a failure costs."""
    by_lower = {n.lower(): n for n in topic_names}
    merged: dict[str, dict] = {}
    chunk_summaries: list[str] = []
    topic_list = "\n".join(f"- {n}" for n in topic_names) or "(empty -- report new topics only)"

    for text in _chunks(segments, speaker_names):
        data = transform._call_json(
            TOPIC_SYSTEM_PROMPT,
            f"MEETING: {title}\n\nTOPIC LIST:\n{topic_list}\n\nTRANSCRIPT:\n{text}",
            "submit_meeting_topics",
            TOPIC_SCHEMA,
        )
        if (data.get("chunk_summary") or "").strip():
            chunk_summaries.append(data["chunk_summary"].strip())
        for entry in data.get("topics", []):
            name = _clean_name(entry.get("topic", ""))
            if not name:
                continue
            listed = by_lower.get(name.lower())
            key = (listed or name).lower()
            start = max(0.0, float(entry.get("start_ts") or 0))
            end = max(start, float(entry.get("end_ts") or start))
            if duration:
                start, end = min(start, duration), min(end, duration)
            summary = (entry.get("summary") or "").strip()
            found = merged.get(key)
            if found is None:
                merged[key] = {"topic": listed, "name": listed or name, "summary": summary, "start_ts": start, "end_ts": end}
            else:
                found["start_ts"], found["end_ts"] = min(found["start_ts"], start), max(found["end_ts"], end)
                if summary and summary not in found["summary"]:
                    found["summary"] = f"{found['summary']} {summary}".strip()[:MAX_TOPIC_SUMMARY_CHARS]

    if len(chunk_summaries) > 1:
        overview = transform._call_json(
            SUMMARY_SYSTEM_PROMPT,
            f"MEETING: {title}\n\nNOTES:\n" + "\n\n".join(chunk_summaries),
            "submit_meeting_summary",
            SUMMARY_SCHEMA,
        ).get("summary", "")
    else:
        overview = chunk_summaries[0] if chunk_summaries else ""
    return {"summary": overview.strip(), "topics": list(merged.values())}


# --- tagging a stored meeting -----------------------------------------------


def tag_meeting(meeting_id: str | uuid.UUID) -> list[str]:
    """(Re)tags a meeting from its stored transcript: sets its summary,
    replaces its topics, and records unlisted subjects as suggestions.
    Returns the slugs of the listed topics it got. Raises on an LLM failure
    without changing anything."""
    session = get_session()
    try:
        meeting = session.get(AgencyMeeting, meeting_id)
        if not meeting or not meeting.transcript:
            return []
        transcript = meeting.transcript
        topics = session.execute(select(Topic).where(Topic.active.is_(True))).scalars().all()
        result = analyze(
            meeting.title,
            transcript.get("segments", []),
            transcript.get("speaker_names", {}),
            [t.name for t in topics],
            meeting.duration_seconds,
        )
        by_name = {t.name: t for t in topics}
        session.query(AgencyMeetingTopic).filter(AgencyMeetingTopic.meeting_id == meeting.id).delete()
        slugs = []
        attached: set = set()
        for entry in result["topics"]:
            topic = by_name.get(entry["topic"]) if entry["topic"] else None
            if topic is None and settings.TOPICS_AUTO_CREATE:
                topic = _auto_create_topic(session, entry["name"])
                if topic is None:
                    continue  # not a usable name, or an admin turned that topic off
            if topic is not None:
                if topic.id in attached:
                    continue  # two labels that slugify the same
                attached.add(topic.id)
                session.add(
                    AgencyMeetingTopic(
                        meeting_id=meeting.id,
                        topic_id=topic.id,
                        summary=entry["summary"],
                        start_ts=entry["start_ts"],
                        end_ts=entry["end_ts"],
                    )
                )
                slugs.append(topic.slug)
            else:
                _record_suggestion(session, entry["name"], meeting.id)
        meeting.summary = result["summary"] or meeting.summary
        session.commit()
        return slugs
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _auto_create_topic(session, name: str) -> Topic | None:
    """The active topic for a subject the model found that wasn't on the list:
    an existing one if the slug matches (the model reworded it), else a new
    one. None for an unusable name or a topic an admin deactivated."""
    name = _clean_name(name)
    slug = slugify(name)
    if not slug:
        return None
    topic = session.execute(select(Topic).where(Topic.slug == slug)).scalar_one_or_none()
    if topic is not None:
        return topic if topic.active else None
    topic = Topic(slug=slug, name=name, description="")
    session.add(topic)
    session.flush()
    # It no longer needs an admin's decision.
    session.query(TopicSuggestion).filter(func.lower(TopicSuggestion.name) == name.lower(), TopicSuggestion.status == "pending").update(
        {"status": "approved"}, synchronize_session=False
    )
    return topic


def _record_suggestion(session, name: str, meeting_id) -> None:
    existing = session.execute(select(TopicSuggestion).where(func.lower(TopicSuggestion.name) == name.lower())).scalar_one_or_none()
    if existing is None:
        session.add(TopicSuggestion(name=name, example_meeting_id=meeting_id))
    elif existing.status == "pending":
        existing.mentions += 1


# --- topic list (admin) -----------------------------------------------------


def _topic_to_dict(topic: Topic) -> dict:
    return {
        "id": str(topic.id),
        "slug": topic.slug,
        "name": topic.name,
        "description": topic.description,
        "active": topic.active,
    }


class TopicError(ValueError):
    """Message is safe to show an admin."""


def create_topic(name: str, description: str = "") -> dict:
    name = _clean_name(name)
    slug = slugify(name)
    if not slug:
        raise TopicError("A topic needs a name.")
    session = get_session()
    try:
        if session.execute(select(Topic.id).where(Topic.slug == slug)).first():
            raise TopicError("There's already a topic with that name.")
        topic = Topic(slug=slug, name=name, description=description.strip())
        session.add(topic)
        session.commit()
        return _topic_to_dict(topic)
    finally:
        session.close()


def update_topic(topic_id: str, name: str | None = None, description: str | None = None, active: bool | None = None) -> dict | None:
    session = get_session()
    try:
        topic = _get(session, Topic, topic_id)
        if not topic:
            return None
        if name is not None:
            cleaned = _clean_name(name)
            if not cleaned:
                raise TopicError("A topic needs a name.")
            topic.name = cleaned  # the slug stays: URLs and links keep working
        if description is not None:
            topic.description = description.strip()
        if active is not None:
            topic.active = active
        session.commit()
        return _topic_to_dict(topic)
    finally:
        session.close()


def _get(session, model, raw_id):
    try:
        return session.get(model, uuid.UUID(str(raw_id)))
    except ValueError:
        return None


def list_topics(active_only: bool = True) -> list[dict]:
    """Topics with how many ready meetings and subscribers each has."""
    session = get_session()
    try:
        query = select(Topic).order_by(Topic.name)
        if active_only:
            query = query.where(Topic.active.is_(True))
        rows = session.execute(query).scalars().all()
        meeting_counts = dict(
            session.execute(
                select(AgencyMeetingTopic.topic_id, func.count())
                .join(AgencyMeeting, AgencyMeeting.id == AgencyMeetingTopic.meeting_id)
                .where(AgencyMeeting.status == "ready")
                .group_by(AgencyMeetingTopic.topic_id)
            ).all()
        )
        subscriber_counts = dict(
            session.execute(select(TopicSubscription.topic_id, func.count()).group_by(TopicSubscription.topic_id)).all()
        )
        return [
            {**_topic_to_dict(t), "meeting_count": meeting_counts.get(t.id, 0), "subscriber_count": subscriber_counts.get(t.id, 0)}
            for t in rows
        ]
    finally:
        session.close()


def get_topic_by_slug(slug: str) -> dict | None:
    session = get_session()
    try:
        topic = session.execute(select(Topic).where(Topic.slug == slug, Topic.active.is_(True))).scalar_one_or_none()
        return _topic_to_dict(topic) if topic else None
    finally:
        session.close()


def list_suggestions(status: str = "pending") -> list[dict]:
    session = get_session()
    try:
        rows = (
            session.query(TopicSuggestion)
            .filter(TopicSuggestion.status == status)
            .order_by(TopicSuggestion.mentions.desc(), TopicSuggestion.created_at)
            .all()
        )
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "mentions": r.mentions,
                "example_meeting_id": str(r.example_meeting_id) if r.example_meeting_id else None,
            }
            for r in rows
        ]
    finally:
        session.close()


def resolve_suggestion(suggestion_id: str, approve: bool) -> dict | None:
    """Approving creates the topic (existing meetings are not re-tagged --
    an admin re-runs tagging on the ones that matter). Returns the new topic,
    or {} for a rejection, or None if there's no such pending suggestion."""
    session = get_session()
    try:
        suggestion = _get(session, TopicSuggestion, suggestion_id)
        if not suggestion or suggestion.status != "pending":
            return None
        suggestion.status = "approved" if approve else "rejected"
        session.commit()
        name = suggestion.name
    finally:
        session.close()
    if not approve:
        return {}
    try:
        return create_topic(name)
    except TopicError:
        return {}  # a topic by that name already exists -- nothing to add


# --- subscriptions ----------------------------------------------------------


def get_subscriptions(user_id: str) -> list[str]:
    """Topic ids the user follows."""
    session = get_session()
    try:
        rows = session.execute(select(TopicSubscription.topic_id).where(TopicSubscription.user_id == uuid.UUID(str(user_id)))).scalars().all()
        return [str(r) for r in rows]
    finally:
        session.close()


def set_subscriptions(user_id: str, topic_ids: list[str]) -> list[str]:
    """Replaces the user's subscriptions with the given (active) topics and
    returns the ids actually saved -- unknown or inactive ids are dropped."""
    wanted = set()
    for raw in topic_ids:
        try:
            wanted.add(uuid.UUID(str(raw)))
        except ValueError:
            continue
    uid = uuid.UUID(str(user_id))
    session = get_session()
    try:
        valid = set(session.execute(select(Topic.id).where(Topic.id.in_(wanted), Topic.active.is_(True))).scalars().all()) if wanted else set()
        session.query(TopicSubscription).filter(TopicSubscription.user_id == uid).delete()
        for topic_id in valid:
            session.add(TopicSubscription(user_id=uid, topic_id=topic_id))
        session.commit()
        return sorted(str(t) for t in valid)
    finally:
        session.close()


# --- public queries ---------------------------------------------------------


def _meeting_card(meeting: AgencyMeeting, agency_name: str) -> dict:
    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "agency": agency_name,
        "meeting_date": meeting.meeting_date,
        "duration_seconds": meeting.duration_seconds,
        "summary": meeting.summary,
    }


def list_meetings_for_topic(slug: str, limit: int = 20, offset: int = 0) -> list[dict] | None:
    """Ready, un-hidden meetings that covered the topic, newest first. None if
    there's no such topic."""
    from .models import MeetingSource

    session = get_session()
    try:
        topic = session.execute(select(Topic).where(Topic.slug == slug, Topic.active.is_(True))).scalar_one_or_none()
        if not topic:
            return None
        rows = session.execute(
            select(AgencyMeeting, MeetingSource.agency_name, AgencyMeetingTopic.summary, AgencyMeetingTopic.start_ts)
            .join(AgencyMeetingTopic, AgencyMeetingTopic.meeting_id == AgencyMeeting.id)
            .join(MeetingSource, MeetingSource.id == AgencyMeeting.source_id)
            .where(AgencyMeetingTopic.topic_id == topic.id, AgencyMeeting.status == "ready")
            .order_by(func.coalesce(AgencyMeeting.meeting_date, AgencyMeeting.created_at).desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [{**_meeting_card(m, agency), "topic_summary": summary, "start_ts": start} for m, agency, summary, start in rows]
    finally:
        session.close()


def get_public_meeting(meeting_id: str) -> dict | None:
    """Everything the public meeting page shows, or None if it doesn't exist
    or isn't public (only `ready` meetings are)."""
    from .models import MeetingSource

    session = get_session()
    try:
        meeting = _get(session, AgencyMeeting, meeting_id)
        if not meeting or meeting.status != "ready":
            return None
        source = session.get(MeetingSource, meeting.source_id)
        topic_rows = session.execute(
            select(Topic, AgencyMeetingTopic)
            .join(AgencyMeetingTopic, AgencyMeetingTopic.topic_id == Topic.id)
            .where(AgencyMeetingTopic.meeting_id == meeting.id)
            .order_by(AgencyMeetingTopic.start_ts)
        ).all()
        transcript = meeting.transcript or {}
        names = transcript.get("speaker_names", {})
        return {
            **_meeting_card(meeting, source.agency_name if source else ""),
            "source_url": meeting.source_url,
            "topics": [
                {"slug": t.slug, "name": t.name, "summary": link.summary, "start_ts": link.start_ts, "end_ts": link.end_ts}
                for t, link in topic_rows
            ],
            "segments": [
                {
                    "speaker": names.get(s.get("speaker"), s.get("speaker")),
                    "text": s.get("text", ""),
                    "start_ts": s.get("start_ts"),
                }
                for s in transcript.get("segments", [])
            ],
        }
    finally:
        session.close()

