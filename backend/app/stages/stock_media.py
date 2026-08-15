"""Match each scene (job_type == "video_gen") to stock visuals via the Pexels
API -- plain `requests` calls, no SDK, matching transcribe.py's existing
pattern for external HTTP APIs (e.g. transcribe_baseten). Landscape/16:9 only
in v1 (see config.py's aspect_ratio note); orientation isn't yet parameterized
off the job's aspect_ratio.

Tries video search first (stock video already has natural motion, no Ken
Burns needed), falls back to photo search (render_scene.py adds the Ken Burns
pan/zoom), falls back to a plain gradient card (media_kind="none") if nothing
matches or every download fails -- a scene can never block the job just
because stock media wasn't found for it.

Downloads 2-3 candidates per scene (not just the top hit) so the review UI
can offer a "pick a different one" swap without a second network round-trip.
"""

from pathlib import Path

import requests

from ..config import settings

PEXELS_PHOTO_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
CANDIDATES_PER_SCENE = 3
REQUEST_TIMEOUT_SECONDS = 15
DOWNLOAD_TIMEOUT_SECONDS = 30


def search_photos(query: str, orientation: str = "landscape") -> list[dict]:
    # No PEXELS_API_KEY configured -- degrade to media_kind="none" (a plain
    # gradient card) for every scene, same as a search that simply found no
    # match. Stock media is an enhancement, not a hard requirement to
    # produce a video, so this is never worth failing the whole job over.
    if not settings.PEXELS_API_KEY:
        return []
    try:
        response = requests.get(
            PEXELS_PHOTO_SEARCH_URL,
            headers={"Authorization": settings.PEXELS_API_KEY},
            params={"query": query, "orientation": orientation, "per_page": CANDIDATES_PER_SCENE},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []
    return response.json().get("photos", [])


def search_videos(query: str, min_duration: float, orientation: str = "landscape") -> list[dict]:
    if not settings.PEXELS_API_KEY:
        return []
    try:
        response = requests.get(
            PEXELS_VIDEO_SEARCH_URL,
            headers={"Authorization": settings.PEXELS_API_KEY},
            params={"query": query, "orientation": orientation, "per_page": CANDIDATES_PER_SCENE},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []
    videos = response.json().get("videos", [])
    # Loopable via -stream_loop in render_scene.py, but prefer clips that
    # already cover the scene without looping when available.
    return sorted(videos, key=lambda v: v.get("duration", 0) < min_duration)


def _best_video_file(video: dict) -> dict | None:
    files = [f for f in video.get("video_files", []) if f.get("link")]
    if not files:
        return None
    # Prefer the file closest to (but not below) 1920px wide, matching
    # render_scene.py's target resolution -- avoids upscaling a low-res file.
    files.sort(key=lambda f: (f.get("width", 0) < 1920, abs(f.get("width", 0) - 1920)))
    return files[0]


def _download(url: str, dest_path: Path) -> bool:
    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS, stream=True)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return False
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 64):
            f.write(chunk)
    return True


def fetch_scene_media(scene: dict, media_dir: Path) -> dict:
    """Downloads up to CANDIDATES_PER_SCENE candidate assets for one scene,
    returning {"media_kind": "video"|"photo"|"none", "candidates": [str paths],
    "chosen_index": 0}. media_kind="none" (render_scene.py draws a gradient
    card) if no video or photo candidates were found or downloaded."""
    scene_id = scene["id"]
    duration = scene["end_ts"] - scene["start_ts"]

    videos = search_videos(scene["query"], min_duration=duration)
    candidates: list[str] = []
    for i, video in enumerate(videos[:CANDIDATES_PER_SCENE]):
        best = _best_video_file(video)
        if not best:
            continue
        dest = media_dir / f"scene_{scene_id}_candidate_{i}.mp4"
        if _download(best["link"], dest):
            candidates.append(str(dest))
    if candidates:
        return {"media_kind": "video", "candidates": candidates, "chosen_index": 0}

    photos = search_photos(scene["query"])
    for i, photo in enumerate(photos[:CANDIDATES_PER_SCENE]):
        src = photo.get("src", {}).get("original")
        if not src:
            continue
        dest = media_dir / f"scene_{scene_id}_candidate_{i}.jpg"
        if _download(src, dest):
            candidates.append(str(dest))
    if candidates:
        return {"media_kind": "photo", "candidates": candidates, "chosen_index": 0}

    return {"media_kind": "none", "candidates": [], "chosen_index": 0}
