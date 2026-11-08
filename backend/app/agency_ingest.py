"""Public agency meetings: watch recording archives, run each new recording
through the normal pipeline, and publish the result.

A tick of run_loop (a daemon thread in worker.py, like review_reminders) does
three things:
  1. poll_source: list each due source's newest recordings and record the new
     ones as `discovered` AgencyMeetings (recordings that are too old, live,
     too long or filtered out by title are `skipped`, so they aren't looked up
     again).
  2. queue_discovered: turn discovered meetings into owner-less audio jobs, at
     most AGENCY_MAX_NEW_PER_DAY a day -- the spending cap.
  3. reconcile: for meetings whose job finished, copy the transcript into the
     meeting row, tag it (topics.py) and queue the topic alerts
     (topic_alerts.py); for failed jobs, record the error.
Reconciling from here rather than hooking the pipeline means the pipeline
doesn't know this exists, and a crashed tick just picks up where it stopped.
"""

import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import direct_media, jobs, topic_alerts, topics, youtube
from .config import settings
from .db import get_session
from .models import AgencyMeeting, Job, MeetingSource

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
# How many of a feed's newest recordings each poll looks at.
FEED_LIMIT = 30
LIVE_STATUSES = ("is_live", "is_upcoming")


class IngestError(ValueError):
    """Message is safe to show an admin."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(session, model, raw_id):
    try:
        return session.get(model, uuid.UUID(str(raw_id)))
    except ValueError:
        return None


# --- sources ----------------------------------------------------------------


def _source_to_dict(source: MeetingSource) -> dict:
    return {
        "id": str(source.id),
        "agency_name": source.agency_name,
        "slug": source.slug,
        "adapter": source.adapter,
        "feed_url": source.feed_url,
        "title_filter": source.title_filter,
        "enabled": source.enabled,
        "last_polled_at": source.last_polled_at,
    }


def _validated_filter(title_filter: str | None) -> str | None:
    title_filter = (title_filter or "").strip() or None
    if title_filter:
        try:
            re.compile(title_filter)
        except re.error:
            raise IngestError("The title filter isn't a valid regular expression.")
    return title_filter


def create_source(agency_name: str, feed_url: str, title_filter: str | None = None) -> dict:
    agency_name = " ".join(agency_name.split())
    slug = topics.slugify(agency_name)
    if not slug:
        raise IngestError("A source needs an agency name.")
    if not youtube.is_youtube_url(feed_url):
        raise IngestError("Only YouTube channel or playlist links are supported so far.")
    session = get_session()
    try:
        if session.execute(select(MeetingSource.id).where(MeetingSource.slug == slug)).first():
            raise IngestError("There's already a source with that agency name.")
        source = MeetingSource(
            agency_name=agency_name, slug=slug, adapter="youtube", feed_url=feed_url.strip(),
            title_filter=_validated_filter(title_filter),
        )
        session.add(source)
        session.commit()
        return _source_to_dict(source)
    finally:
        session.close()


def update_source(source_id: str, **fields) -> dict | None:
    """Fields: agency_name (display only -- the slug stays), feed_url,
    title_filter, enabled."""
    session = get_session()
    try:
        source = _get(session, MeetingSource, source_id)
        if not source:
            return None
        if fields.get("agency_name") is not None:
            name = " ".join(fields["agency_name"].split())
            if not name:
                raise IngestError("A source needs an agency name.")
            source.agency_name = name
        if fields.get("feed_url") is not None:
            if not youtube.is_youtube_url(fields["feed_url"]):
                raise IngestError("Only YouTube channel or playlist links are supported so far.")
            source.feed_url = fields["feed_url"].strip()
        if "title_filter" in fields:
            source.title_filter = _validated_filter(fields["title_filter"])
        if fields.get("enabled") is not None:
            source.enabled = fields["enabled"]
        session.commit()
        return _source_to_dict(source)
    finally:
        session.close()


def list_sources() -> list[dict]:
    session = get_session()
    try:
        return [_source_to_dict(s) for s in session.query(MeetingSource).order_by(MeetingSource.agency_name).all()]
    finally:
        session.close()


def delete_source(source_id: str) -> bool:
    """Also deletes the source's meetings (cascade)."""
    session = get_session()
    try:
        source = _get(session, MeetingSource, source_id)
        if not source:
            return False
        session.delete(source)
        session.commit()
        return True
    finally:
        session.close()


# --- discovering recordings -------------------------------------------------


def _parse_upload_date(meta: dict) -> datetime | None:
    raw = meta.get("upload_date")
    if raw:
        try:
            return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    timestamp = meta.get("release_timestamp") or meta.get("timestamp")
    return datetime.fromtimestamp(timestamp, timezone.utc) if timestamp else None


def poll_source(source: dict) -> int:
    """Records the source's new recordings. Returns how many are now
    `discovered`. A feed that can't be read is logged and skipped."""
    cutoff = _now() - timedelta(days=settings.AGENCY_BACKFILL_DAYS)
    try:
        entries = youtube.list_feed_entries(source["feed_url"], FEED_LIMIT)
    except youtube.YoutubeDownloadError:
        logger.exception("Couldn't list %s", source["feed_url"])
        entries = []
    session = get_session()
    try:
        known = set(
            session.execute(select(AgencyMeeting.external_id).where(AgencyMeeting.source_id == uuid.UUID(source["id"]))).scalars().all()
        )
    finally:
        session.close()

    discovered = 0
    for entry in entries:
        if entry["id"] in known:
            continue
        title = entry["title"]
        if source["title_filter"] and not re.search(source["title_filter"], title, re.IGNORECASE):
            _insert_meeting(source["id"], entry["id"], title, entry["url"], status="skipped")
            continue
        try:
            meta = youtube.fetch_metadata(entry["url"])
        except youtube.YoutubeDownloadError:
            logger.warning("No metadata for %s -- will try again next poll", entry["url"])
            continue
        if meta.get("live_status") in LIVE_STATUSES:
            continue  # not a recording yet; it shows up as a normal video afterwards
        published = _parse_upload_date(meta)
        duration = meta.get("duration")
        status, error = "discovered", None
        if published is not None and published < cutoff:
            status = "skipped"
        elif duration and duration > settings.AGENCY_MAX_DURATION_SECONDS:
            status, error = "skipped", "Longer than the maximum meeting length"
        if _insert_meeting(
            source["id"], entry["id"], meta.get("title") or title, entry["url"],
            status=status, meeting_date=published, duration=duration, error=error,
        ) and status == "discovered":
            discovered += 1
    _mark_polled(source["id"])
    return discovered


def _insert_meeting(source_id, external_id, title, url, status, meeting_date=None, duration=None, error=None) -> str | None:
    session = get_session()
    try:
        meeting = AgencyMeeting(
            source_id=uuid.UUID(str(source_id)), external_id=external_id, title=title or "Untitled meeting",
            source_url=url, status=status, meeting_date=meeting_date, duration_seconds=duration, error_message=error,
        )
        session.add(meeting)
        session.commit()
        return str(meeting.id)
    except Exception:
        session.rollback()  # most likely a concurrent insert of the same recording
        logger.warning("Couldn't record meeting %s", external_id, exc_info=True)
        return None
    finally:
        session.close()


def _mark_polled(source_id: str) -> None:
    session = get_session()
    try:
        source = session.get(MeetingSource, uuid.UUID(str(source_id)))
        if source:
            source.last_polled_at = _now()
            session.commit()
    finally:
        session.close()


def add_meeting_by_url(source_id: str, url: str) -> dict:
    """Admin: add one recording by link (for trying the pipeline on a real
    meeting before polling is on, or to catch one the poller skipped).
    Queued straight away, ignoring the backfill window and daily cap."""
    try:
        if youtube.is_youtube_url(url):
            meta = youtube.fetch_metadata(url)
        elif direct_media.is_direct_url(url):
            # A direct link to the recording file. The length may be unknown
            # until it's downloaded (the worker checks the cap then).
            meta = direct_media.fetch_metadata(url, max_bytes=settings.AGENCY_MAX_DOWNLOAD_BYTES)
            url = meta["url"]
            meta["id"] = "file:" + hashlib.sha1(url.encode()).hexdigest()[:24]
        else:
            raise IngestError("That doesn't look like a link to a video.")
    except (youtube.YoutubeDownloadError, direct_media.DirectMediaError) as e:
        raise IngestError(str(e))
    duration = meta.get("duration")
    if duration and duration > settings.AGENCY_MAX_DURATION_SECONDS:
        raise IngestError("That recording is longer than the maximum meeting length.")
    session = get_session()
    try:
        if not _get(session, MeetingSource, source_id):
            raise IngestError("No such source.")
        existing = session.execute(
            select(AgencyMeeting).where(
                AgencyMeeting.source_id == uuid.UUID(str(source_id)), AgencyMeeting.external_id == meta["id"]
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status not in ("skipped", "failed"):
            raise IngestError("That recording has already been added.")
        if existing is not None:
            meeting_id = str(existing.id)
            existing.status, existing.error_message, existing.job_id = "discovered", None, None
            session.commit()
        else:
            meeting_id = None
    finally:
        session.close()
    if meeting_id is None:
        meeting_id = _insert_meeting(
            source_id, meta["id"], meta.get("title"), url, status="discovered",
            meeting_date=_parse_upload_date(meta), duration=duration,
        )
        if meeting_id is None:
            raise IngestError("Couldn't add that recording.")
    _queue_job(meeting_id)
    return get_meeting(meeting_id)


# --- queueing and finishing -------------------------------------------------


def get_meeting_id_by_job(job_id: str) -> str | None:
    session = get_session()
    try:
        found = session.execute(select(AgencyMeeting.id).where(AgencyMeeting.job_id == job_id)).scalar_one_or_none()
        return str(found) if found else None
    finally:
        session.close()


def _queue_job(meeting_id: str) -> str | None:
    """Creates the pipeline job for a discovered meeting: an audio job (diarized
    transcript with speaker names, no frames, nothing to review), owned by
    nobody and billed nothing."""
    session = get_session()
    try:
        meeting = _get(session, AgencyMeeting, meeting_id)
        if not meeting or meeting.status != "discovered":
            return None
        job_id = str(uuid.uuid4())
        jobs.create_job(
            job_id, None, user_id=None, billed_cents=0, title=meeting.title, job_type="audio",
            source_url=meeting.source_url, extract_frames=False,
        )
        meeting.job_id = job_id
        meeting.status = "processing"
        session.commit()
        return job_id
    finally:
        session.close()


def queue_discovered() -> int:
    """Queues discovered meetings, newest first, up to the daily cap."""
    session = get_session()
    try:
        used = session.execute(
            select(func.count())
            .select_from(AgencyMeeting)
            .join(Job, Job.id == AgencyMeeting.job_id)
            .where(Job.created_at > _now() - timedelta(hours=24))
        ).scalar()
        room = max(0, settings.AGENCY_MAX_NEW_PER_DAY - (used or 0))
        if not room:
            return 0
        ids = session.execute(
            select(AgencyMeeting.id)
            .where(AgencyMeeting.status == "discovered")
            .order_by(func.coalesce(AgencyMeeting.meeting_date, AgencyMeeting.created_at).desc())
            .limit(room)
        ).scalars().all()
    finally:
        session.close()
    return sum(1 for meeting_id in ids if _queue_job(str(meeting_id)))


def reconcile() -> int:
    """Finishes meetings whose job has ended. Returns how many became ready."""
    session = get_session()
    try:
        processing = [
            (str(m.id), m.job_id)
            for m in session.query(AgencyMeeting).filter(AgencyMeeting.status == "processing").all()
        ]
    finally:
        session.close()
    ready = 0
    for meeting_id, job_id in processing:
        try:
            ready += 1 if finish_meeting(meeting_id, job_id) else 0
        except Exception:
            logger.exception("Couldn't finish agency meeting %s", meeting_id)
    return ready


def _set_failed(meeting_id: str, error: str) -> None:
    session = get_session()
    try:
        meeting = session.get(AgencyMeeting, uuid.UUID(meeting_id))
        meeting.status, meeting.error_message = "failed", error[:500]
        session.commit()
    finally:
        session.close()


def finish_meeting(meeting_id: str, job_id: str | None) -> bool:
    """Looks at the meeting's job. Done: stores the transcript, tags, marks the
    meeting ready (public) and queues its alerts -> True. Failed: records why.
    Still running: nothing."""
    job = jobs.get_job(job_id) if job_id else None
    if job is None:
        _set_failed(meeting_id, "The processing job is missing.")
        return False
    if job["status"] in ("failed", "cancelled"):
        _set_failed(meeting_id, job.get("error_message") or f"Processing {job['status']}.")
        return False
    if job["status"] != "done":
        return False

    transcript_path = settings.OUTPUT_DIR / job["id"] / "document" / "transcript.json"
    try:
        transcript = json.loads(transcript_path.read_text())
    except (OSError, ValueError):
        _set_failed(meeting_id, "The finished job has no transcript.")
        return False

    session = get_session()
    try:
        meeting = session.get(AgencyMeeting, uuid.UUID(meeting_id))
        meeting.transcript = {
            "segments": transcript.get("segments", []),
            "speaker_names": transcript.get("speaker_names", {}),
        }
        meeting.duration_seconds = job.get("duration_seconds") or meeting.duration_seconds
        session.commit()
    finally:
        session.close()

    # A tagging failure (LLM outage) leaves the meeting public but untagged
    # and silent; an admin re-runs it with retag().
    try:
        topics.tag_meeting(meeting_id)
    except Exception:
        logger.exception("Tagging agency meeting %s failed", meeting_id)

    session = get_session()
    try:
        meeting = session.get(AgencyMeeting, uuid.UUID(meeting_id))
        meeting.status, meeting.error_message, meeting.processed_at = "ready", None, _now()
        session.commit()
    finally:
        session.close()
    topic_alerts.queue_for_meeting(meeting_id)
    return True


def retag(meeting_id: str) -> bool:
    """Admin: tag a ready meeting again (after an LLM failure, or new topics)
    and queue alerts for anyone it now matches. Raises on an LLM failure."""
    session = get_session()
    try:
        meeting = _get(session, AgencyMeeting, meeting_id)
        if not meeting or meeting.status != "ready":
            return False
    finally:
        session.close()
    topics.tag_meeting(meeting_id)
    topic_alerts.queue_for_meeting(meeting_id)
    return True


def retry_failed(meeting_id: str) -> bool:
    session = get_session()
    try:
        meeting = _get(session, AgencyMeeting, meeting_id)
        if not meeting or meeting.status != "failed":
            return False
        meeting.status, meeting.error_message, meeting.job_id = "discovered", None, None
        session.commit()
    finally:
        session.close()
    return bool(_queue_job(meeting_id))


def set_hidden(meeting_id: str, hidden: bool) -> bool:
    """Admin takedown / restore. Restoring only works for a meeting that had
    finished processing (it has a transcript)."""
    session = get_session()
    try:
        meeting = _get(session, AgencyMeeting, meeting_id)
        if not meeting:
            return False
        if hidden:
            meeting.status = "hidden"
        elif meeting.status == "hidden" and meeting.transcript:
            meeting.status = "ready"
        else:
            return False
        session.commit()
        return True
    finally:
        session.close()


def _meeting_to_dict(meeting: AgencyMeeting, agency_name: str) -> dict:
    return {
        "id": str(meeting.id),
        "source_id": str(meeting.source_id),
        "agency": agency_name,
        "title": meeting.title,
        "meeting_date": meeting.meeting_date,
        "source_url": meeting.source_url,
        "job_id": meeting.job_id,
        "status": meeting.status,
        "duration_seconds": meeting.duration_seconds,
        "has_summary": bool(meeting.summary),
        "error_message": meeting.error_message,
        "processed_at": meeting.processed_at,
        "created_at": meeting.created_at,
    }


def get_meeting(meeting_id: str) -> dict | None:
    session = get_session()
    try:
        meeting = _get(session, AgencyMeeting, meeting_id)
        if not meeting:
            return None
        source = session.get(MeetingSource, meeting.source_id)
        return _meeting_to_dict(meeting, source.agency_name if source else "")
    finally:
        session.close()


def list_meetings(status: str | None = None, limit: int = 100) -> list[dict]:
    session = get_session()
    try:
        query = (
            select(AgencyMeeting, MeetingSource.agency_name)
            .join(MeetingSource, MeetingSource.id == AgencyMeeting.source_id)
            .order_by(func.coalesce(AgencyMeeting.meeting_date, AgencyMeeting.created_at).desc())
            .limit(limit)
        )
        if status:
            query = query.where(AgencyMeeting.status == status)
        return [_meeting_to_dict(m, name) for m, name in session.execute(query).all()]
    finally:
        session.close()


# --- the loop ---------------------------------------------------------------


def _due_sources() -> list[dict]:
    due_before = _now() - timedelta(seconds=settings.AGENCY_POLL_INTERVAL_SECONDS)
    return [
        s for s in list_sources()
        if s["enabled"] and (s["last_polled_at"] is None or s["last_polled_at"] < due_before)
    ]


def run_once() -> None:
    """One tick. Polling and queueing only happen while AGENCY_INGEST_ENABLED;
    finishing meetings already in flight always does, so turning ingest off
    never strands a job."""
    if settings.AGENCY_INGEST_ENABLED:
        for source in _due_sources():
            try:
                found = poll_source(source)
                if found:
                    logger.info("%s: %d new recording(s)", source["agency_name"], found)
            except Exception:
                logger.exception("Polling %s failed", source["agency_name"])
        queue_discovered()
    reconcile()


def run_loop() -> None:
    """Blocking loop for a daemon thread in worker.py -- its own thread
    because the main worker loop blocks for a job's full processing time."""
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Agency ingest tick failed")
        time.sleep(TICK_SECONDS)
