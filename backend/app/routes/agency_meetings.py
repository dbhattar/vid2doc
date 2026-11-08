"""Public agency meetings: the topic list and meeting pages anyone can read,
and the signed-in user's topic subscriptions. See app/agency_ingest.py and
app/topics.py."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import topics
from ..deps import get_current_user

router = APIRouter()


@router.get("/api/public/topics")
def list_public_topics() -> dict:
    return {
        "topics": [
            {k: t[k] for k in ("id", "slug", "name", "description", "meeting_count")} for t in topics.list_topics()
        ]
    }


@router.get("/api/public/topics/{slug}")
def get_public_topic(slug: str) -> dict:
    topic = topics.get_topic_by_slug(slug)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {k: topic[k] for k in ("id", "slug", "name", "description")}


@router.get("/api/public/topics/{slug}/meetings")
def list_topic_meetings(
    slug: str, limit: int = Query(default=20, ge=1, le=50), offset: int = Query(default=0, ge=0)
) -> dict:
    meetings = topics.list_meetings_for_topic(slug, limit, offset)
    if meetings is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"meetings": meetings}


@router.get("/api/public/agency-meetings/{meeting_id}")
def get_public_meeting(meeting_id: str) -> dict:
    meeting = topics.get_public_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


class SubscriptionsRequest(BaseModel):
    topic_ids: list[str] = Field(max_length=200)


@router.get("/api/me/topic-subscriptions")
def get_subscriptions(current_user: dict = Depends(get_current_user)) -> dict:
    return {"topic_ids": topics.get_subscriptions(current_user["id"])}


@router.put("/api/me/topic-subscriptions")
def set_subscriptions(body: SubscriptionsRequest, current_user: dict = Depends(get_current_user)) -> dict:
    return {"topic_ids": topics.set_subscriptions(current_user["id"], body.topic_ids)}
