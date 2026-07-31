"""Frame review for video jobs paused at status="awaiting_review" -- list the
candidate frames a job's pipeline stopped on, serve their images, let the
user include/exclude and re-caption them, and resume the job once submitted.
See pipeline.py's run_job/resume_after_review for the other half of this.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .. import jobs
from ..config import settings
from ..deps import get_current_user
from ..stages import assemble

router = APIRouter()


def _owned_review_job(job_id: str, current_user: dict) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"] or job["status"] != "awaiting_review":
        raise HTTPException(status_code=404, detail="Review not found")
    return job


def _review_path(job_id: str):
    return settings.OUTPUT_DIR / job_id / "review.json"


def _load_review(job_id: str) -> dict:
    path = _review_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Review not found")
    return json.loads(path.read_text())


def _save_review(job_id: str, data: dict) -> None:
    _review_path(job_id).write_text(json.dumps(data, indent=2))


def _find_item(data: dict, item_id: int) -> dict | None:
    return next((item for item in data["items"] if item["id"] == item_id), None)


@router.get("/api/jobs/{job_id}/review")
def get_review(job_id: str, current_user: dict = Depends(get_current_user)):
    _owned_review_job(job_id, current_user)
    data = _load_review(job_id)
    # Never leak raw filesystem paths -- the frontend fetches each frame's
    # image via the dedicated route below instead.
    return {"items": [{k: v for k, v in item.items() if k != "path"} for item in data["items"]]}


@router.get("/api/jobs/{job_id}/review/frames/{item_id}")
def get_review_frame(job_id: str, item_id: int, current_user: dict = Depends(get_current_user)):
    """Serves one candidate's source image -- doubles as both the review
    grid's thumbnail source and "save this frame individually"."""
    _owned_review_job(job_id, current_user)
    data = _load_review(job_id)
    item = _find_item(data, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(item["path"])


class ReviewItemUpdate(BaseModel):
    id: int
    included: bool


class SubmitReviewRequest(BaseModel):
    items: list[ReviewItemUpdate]


@router.post("/api/jobs/{job_id}/review")
def submit_review(job_id: str, body: SubmitReviewRequest, current_user: dict = Depends(get_current_user)):
    _owned_review_job(job_id, current_user)
    data = _load_review(job_id)
    updates = {u.id: u for u in body.items}
    for item in data["items"]:
        update = updates.get(item["id"])
        if update:
            item["included"] = update.included
    _save_review(job_id, data)

    # Re-queue rather than run inline -- composing calls an LLM and could take
    # a while, so this goes through the same worker/poll loop as any other
    # job instead of blocking this request. pipeline.run_job checks this
    # exact progress_stage to skip straight to resume_after_review.
    jobs.update_job(job_id, status="queued", progress_stage="resuming_after_review")
    return jobs.get_job(job_id)


@router.get("/api/jobs/{job_id}/review/tables/{item_id}/markdown")
def get_review_table_markdown(job_id: str, item_id: int, current_user: dict = Depends(get_current_user)):
    """Re-exports a table the classifier already extracted, as a standalone
    markdown file. No LLM call, no charge -- this is a pure formatting export
    of data the normal pipeline run already produced."""
    _owned_review_job(job_id, current_user)
    data = _load_review(job_id)
    item = _find_item(data, item_id)
    if not item or item["kind"] != "table":
        raise HTTPException(status_code=404, detail="Table not found")
    markdown = assemble.render_table_markdown(item, item.get("caption", ""))
    return PlainTextResponse(
        markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="table-{item_id}.md"'},
    )
