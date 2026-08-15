"""Scene review for video_gen jobs paused at status="awaiting_review" -- list
the auto-generated scenes (headline + stock media candidates) a job's
pipeline stopped on, serve the candidate assets, let the user edit headlines
and swap the chosen stock pick, and resume the job once submitted. See
pipeline.py's _transcribe_and_segment_scenes/resume_after_scene_review for
the other half of this.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def _owned_scene_review_job(job_id: str, current_user: dict) -> dict:
    job = jobs.get_job(job_id)
    if (
        not job
        or job["user_id"] != current_user["id"]
        or job["status"] != "awaiting_review"
        or job["job_type"] != "video_gen"
    ):
        raise HTTPException(status_code=404, detail="Scene review not found")
    return job


def _scenes_path(job_id: str):
    return settings.OUTPUT_DIR / job_id / "scenes.json"


def _load_scenes(job_id: str) -> dict:
    path = _scenes_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Scene review not found")
    return json.loads(path.read_text())


def _save_scenes(job_id: str, data: dict) -> None:
    _scenes_path(job_id).write_text(json.dumps(data, indent=2))


def _find_scene(data: dict, scene_id: int) -> dict | None:
    return next((s for s in data["scenes"] if s["id"] == scene_id), None)


@router.get("/api/jobs/{job_id}/scene-review")
def get_scene_review(job_id: str, current_user: dict = Depends(get_current_user)):
    _owned_scene_review_job(job_id, current_user)
    data = _load_scenes(job_id)
    # Never leak raw filesystem paths -- the frontend fetches each candidate
    # asset via the dedicated media route below, by index.
    return {
        "scenes": [
            {
                "id": s["id"],
                "start_ts": s["start_ts"],
                "end_ts": s["end_ts"],
                "headline": s["headline"],
                "media_kind": s["media_kind"],
                "candidate_count": len(s.get("candidates", [])),
                "chosen_index": s.get("chosen_index", 0),
            }
            for s in data["scenes"]
        ]
    }


@router.get("/api/jobs/{job_id}/scene-review/media/{scene_id}")
def get_scene_review_media(
    job_id: str, scene_id: int, candidate_index: int = 0, current_user: dict = Depends(get_current_user)
):
    _owned_scene_review_job(job_id, current_user)
    data = _load_scenes(job_id)
    scene = _find_scene(data, scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    candidates = scene.get("candidates", [])
    if candidate_index < 0 or candidate_index >= len(candidates):
        raise HTTPException(status_code=404, detail="Candidate not found")
    return FileResponse(candidates[candidate_index])


class SceneItemUpdate(BaseModel):
    id: int
    headline: str
    chosen_index: int = 0


class SubmitSceneReviewRequest(BaseModel):
    items: list[SceneItemUpdate]


@router.post("/api/jobs/{job_id}/scene-review")
def submit_scene_review(job_id: str, body: SubmitSceneReviewRequest, current_user: dict = Depends(get_current_user)):
    _owned_scene_review_job(job_id, current_user)
    data = _load_scenes(job_id)
    updates = {u.id: u for u in body.items}
    for scene in data["scenes"]:
        update = updates.get(scene["id"])
        if update:
            scene["headline"] = update.headline
            scene["chosen_index"] = update.chosen_index
    _save_scenes(job_id, data)

    # Re-queue rather than render inline -- ffmpeg rendering is the most
    # CPU-heavy step in the whole pipeline, so this goes through the same
    # worker/poll loop as any other job. pipeline.run_job checks this exact
    # progress_stage to skip straight to resume_after_scene_review.
    jobs.update_job(job_id, status="queued", progress_stage="resuming_after_scene_review")
    return jobs.get_job(job_id)
