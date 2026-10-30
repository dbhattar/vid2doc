"""Topic review for research jobs paused at progress_stage="awaiting_topic_review"
-- list the topics the pipeline proposed, let the user edit/remove/add their
own, and resume the job once confirmed. See pipeline.py's
_pause_for_topic_review/run_job for the other half of this.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import jobs
from ..config import settings
from ..deps import get_current_user
from ..stages import transform
from .status import build_job_response

router = APIRouter()


def _owned_topic_review_job(job_id: str, current_user: dict) -> dict:
    job = jobs.get_job(job_id)
    if (
        not job
        or job["user_id"] != current_user["id"]
        or job["status"] != "awaiting_review"
        or job["progress_stage"] != "awaiting_topic_review"
    ):
        raise HTTPException(status_code=404, detail="Review not found")
    return job


def _topics_path(job_id: str):
    return settings.OUTPUT_DIR / job_id / "topics.json"


@router.get("/api/jobs/{job_id}/topics")
def get_topics(job_id: str, current_user: dict = Depends(get_current_user)):
    _owned_topic_review_job(job_id, current_user)
    path = _topics_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Review not found")
    return {"topics": json.loads(path.read_text())["topics"], "max_topics": transform.RESEARCH_MAX_REVIEWED_TOPICS}


class TopicItem(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    # Empty for a topic the user added themselves.
    context: str = Field(default="", max_length=2000)


class SubmitTopicsRequest(BaseModel):
    topics: list[TopicItem]


@router.post("/api/jobs/{job_id}/topics")
def submit_topics(job_id: str, body: SubmitTopicsRequest, request: Request, current_user: dict = Depends(get_current_user)):
    _owned_topic_review_job(job_id, current_user)
    topics = [{"topic": t.topic.strip(), "context": t.context.strip()} for t in body.topics if t.topic.strip()]
    if not topics:
        raise HTTPException(status_code=400, detail="Pick at least one topic to research.")
    if len(topics) > transform.RESEARCH_MAX_REVIEWED_TOPICS:
        raise HTTPException(
            status_code=400, detail=f"Pick at most {transform.RESEARCH_MAX_REVIEWED_TOPICS} topics."
        )
    _topics_path(job_id).write_text(json.dumps({"topics": topics, "confirmed": True}, indent=2))

    # Re-queue through the normal worker loop -- research is slow. run_job
    # checks this exact progress_stage to resume.
    jobs.update_job(job_id, status="queued", progress_stage="resuming_after_topic_review")
    return build_job_response(jobs.get_job(job_id), request)
