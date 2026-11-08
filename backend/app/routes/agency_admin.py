"""Admin management of public agency meetings: sources to poll, the topic
list, suggested topics, and the meetings themselves. See app/agency_ingest.py."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import agency_ingest, topics
from ..deps import get_current_admin_user

router = APIRouter()


def _guard(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except (agency_ingest.IngestError, topics.TopicError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- sources ---------------------------------------------------------------


class SourceCreate(BaseModel):
    agency_name: str = Field(min_length=1, max_length=120)
    feed_url: str = Field(min_length=1, max_length=500)
    title_filter: str | None = Field(default=None, max_length=200)


class SourceUpdate(BaseModel):
    agency_name: str | None = Field(default=None, max_length=120)
    feed_url: str | None = Field(default=None, max_length=500)
    title_filter: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


@router.get("/api/admin/agency/sources")
def list_sources(current_user: dict = Depends(get_current_admin_user)) -> dict:
    return {"sources": agency_ingest.list_sources()}


@router.post("/api/admin/agency/sources", status_code=201)
def create_source(body: SourceCreate, current_user: dict = Depends(get_current_admin_user)) -> dict:
    return _guard(agency_ingest.create_source, body.agency_name, body.feed_url, body.title_filter)


@router.patch("/api/admin/agency/sources/{source_id}")
def update_source(source_id: str, body: SourceUpdate, current_user: dict = Depends(get_current_admin_user)) -> dict:
    source = _guard(agency_ingest.update_source, source_id, **body.model_dump(exclude_unset=True))
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.delete("/api/admin/agency/sources/{source_id}", status_code=204)
def delete_source(source_id: str, current_user: dict = Depends(get_current_admin_user)) -> None:
    if not agency_ingest.delete_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")


# --- topics ----------------------------------------------------------------


class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class TopicUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None


@router.get("/api/admin/agency/topics")
def list_topics(current_user: dict = Depends(get_current_admin_user)) -> dict:
    return {"topics": topics.list_topics(active_only=False), "suggestions": topics.list_suggestions()}


@router.post("/api/admin/agency/topics", status_code=201)
def create_topic(body: TopicCreate, current_user: dict = Depends(get_current_admin_user)) -> dict:
    return _guard(topics.create_topic, body.name, body.description)


@router.patch("/api/admin/agency/topics/{topic_id}")
def update_topic(topic_id: str, body: TopicUpdate, current_user: dict = Depends(get_current_admin_user)) -> dict:
    topic = _guard(topics.update_topic, topic_id, **body.model_dump(exclude_unset=True))
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.post("/api/admin/agency/suggestions/{suggestion_id}/{action}")
def resolve_suggestion(suggestion_id: str, action: str, current_user: dict = Depends(get_current_admin_user)) -> dict:
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=404, detail="Not found")
    result = topics.resolve_suggestion(suggestion_id, approve=action == "approve")
    if result is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"topic": result or None}


# --- meetings --------------------------------------------------------------


class MeetingAdd(BaseModel):
    source_id: str
    url: str = Field(min_length=1, max_length=500)


@router.get("/api/admin/agency/meetings")
def list_meetings(
    status: str | None = None, limit: int = Query(default=100, ge=1, le=500), current_user: dict = Depends(get_current_admin_user)
) -> dict:
    return {"meetings": agency_ingest.list_meetings(status, limit)}


@router.post("/api/admin/agency/meetings", status_code=201)
def add_meeting(body: MeetingAdd, current_user: dict = Depends(get_current_admin_user)) -> dict:
    return _guard(agency_ingest.add_meeting_by_url, body.source_id, body.url)


@router.post("/api/admin/agency/meetings/{meeting_id}/{action}")
def meeting_action(meeting_id: str, action: str, current_user: dict = Depends(get_current_admin_user)) -> dict:
    """retag | retry | hide | unhide."""
    if action == "retag":
        try:
            done = agency_ingest.retag(meeting_id)
        except Exception:
            raise HTTPException(status_code=502, detail="Tagging failed -- check the LLM provider and try again.")
    elif action == "retry":
        done = agency_ingest.retry_failed(meeting_id)
    elif action in ("hide", "unhide"):
        done = agency_ingest.set_hidden(meeting_id, action == "hide")
    else:
        raise HTTPException(status_code=404, detail="Not found")
    if not done:
        raise HTTPException(status_code=400, detail="That doesn't apply to this meeting's current state.")
    return agency_ingest.get_meeting(meeting_id)
