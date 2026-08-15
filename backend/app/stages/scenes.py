"""Segment a diarized transcript into topic-based scenes for video generation
(job_type == "video_gen") -- each scene becomes exactly one rendered clip (see
render_scene.py), so scenes must tile the whole timeline with no gaps or
overlaps. Reuses compose.py's window-based scaling (~3500 words/window, see
compose._make_windows) so arbitrarily long audio is handled the same proven
way, at roughly constant LLM cost per minute of audio.

The LLM's proposed scene boundaries are only ever a starting point: they're
snapped to real transcript segment boundaries and validated to be a
gap/overlap-free tiling of each window. A window that fails validation falls
back to fixed-length chunking instead of failing the whole job -- segmentation
quality can vary, but the job's ability to produce *some* video shouldn't
depend on the LLM getting the shape exactly right.
"""

import os

from ..config import settings
from ..exceptions import PipelineError
from .compose import _make_windows

FALLBACK_SCENE_SECONDS = 30

SYSTEM_PROMPT = """You are splitting a slice of a spoken-audio transcript into short visual "scenes" for a generated video.

Each scene should cover one coherent idea or beat (typically 5-20 seconds), timed to the transcript's own timestamps. For each scene, give:
- start_ts / end_ts: must exactly match transcript segment boundaries given in this slice -- never a value that falls mid-segment.
- title: a short internal label for this scene's topic (a few words).
- query: 2-4 literal keywords describing what to visually show for this scene, for a stock photo/video search -- concrete and visual (e.g. "city skyline sunset", "laptop coding"), never abstract.

Scenes must be contiguous and cover the entire slice with no gaps or overlaps: the first scene's start_ts must equal the slice's first timestamp, the last scene's end_ts must equal the slice's last timestamp, and each scene's start_ts must equal the previous scene's end_ts."""

SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "start_ts": {"type": "number"},
        "end_ts": {"type": "number"},
        "title": {"type": "string"},
        "query": {"type": "string"},
    },
    "required": ["start_ts", "end_ts", "title", "query"],
}

SEGMENT_TOOL = {
    "name": "submit_scenes",
    "description": "Submit the scenes for this transcript slice.",
    "input_schema": {
        "type": "object",
        "properties": {"scenes": {"type": "array", "items": SCENE_SCHEMA}},
        "required": ["scenes"],
    },
}

SEGMENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {"scenes": {"type": "array", "items": {**SCENE_SCHEMA, "additionalProperties": False}}},
    "required": ["scenes"],
    "additionalProperties": False,
}


def _window_text(window: list[dict]) -> str:
    return "\n".join(f"[{s['start_ts']:.1f}-{s['end_ts']:.1f}s] {s['speaker']}: {s['text']}" for s in window)


def _segment_window_anthropic(client, window: list[dict]) -> list[dict]:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[SEGMENT_TOOL],
        tool_choice={"type": "tool", "name": "submit_scenes"},
        messages=[{"role": "user", "content": _window_text(window)}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input["scenes"]
    return []


def _segment_window_openai(client, window: list[dict]) -> list[dict]:
    import json

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _window_text(window)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "submit_scenes", "strict": True, "schema": SEGMENT_JSON_SCHEMA},
        },
    )
    return json.loads(response.choices[0].message.content)["scenes"]


def _get_client_and_fn(provider: str):
    if provider == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PipelineError("OPENAI_API_KEY is not set")
        return openai.OpenAI(api_key=api_key), _segment_window_openai
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PipelineError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key), _segment_window_anthropic


def _fallback_window_scenes(window: list[dict]) -> list[dict]:
    """Fixed-length (~FALLBACK_SCENE_SECONDS) chunking of one window's
    segments -- guarantees segmentation can never hard-fail the job."""
    scenes = []
    current: list[dict] = []
    current_start = window[0]["start_ts"]
    for seg in window:
        current.append(seg)
        if seg["end_ts"] - current_start >= FALLBACK_SCENE_SECONDS:
            label = current[0]["text"][:40]
            scenes.append({"start_ts": current_start, "end_ts": seg["end_ts"], "title": label, "query": label})
            current = []
            current_start = seg["end_ts"]
    if current:
        label = current[0]["text"][:40]
        scenes.append({"start_ts": current_start, "end_ts": window[-1]["end_ts"], "title": label, "query": label})
    return scenes


def _snap_to_boundary(ts: float, boundaries: list[float]) -> float:
    return min(boundaries, key=lambda b: abs(b - ts))


def _validate_and_snap(scenes: list[dict], window: list[dict]) -> list[dict] | None:
    """Snaps each proposed scene's start_ts/end_ts to the nearest real segment
    boundary in this window, then verifies the result is a valid,
    gap/overlap-free tiling of the window's span. Returns None (caller falls
    back to fixed-length chunking) if it can't be made valid."""
    if not scenes:
        return None
    boundaries = sorted({window[0]["start_ts"]} | {s["end_ts"] for s in window})

    snapped = []
    for s in scenes:
        start = _snap_to_boundary(s["start_ts"], boundaries)
        end = _snap_to_boundary(s["end_ts"], boundaries)
        if end <= start:
            return None
        snapped.append({**s, "start_ts": start, "end_ts": end})
    snapped.sort(key=lambda s: s["start_ts"])

    if snapped[0]["start_ts"] != window[0]["start_ts"] or snapped[-1]["end_ts"] != window[-1]["end_ts"]:
        return None
    for prev, cur in zip(snapped, snapped[1:]):
        if prev["end_ts"] != cur["start_ts"]:
            return None
    return snapped


def segment_scenes(segments: list[dict], provider: str | None = None) -> list[dict]:
    """Splits a full diarized transcript into contiguous scenes tiling
    [0, duration] with no gaps/overlaps. Assigns sequential ids across the
    whole transcript at the end."""
    if not segments:
        return []

    provider = provider or settings.LLM_PROVIDER
    client, segment_window = _get_client_and_fn(provider)

    all_scenes: list[dict] = []
    for window in _make_windows(segments):
        try:
            proposed = segment_window(client, window)
        except Exception:
            proposed = []
        valid = _validate_and_snap(proposed, window)
        all_scenes.extend(valid if valid is not None else _fallback_window_scenes(window))

    for i, scene in enumerate(all_scenes):
        scene["id"] = i
    return all_scenes
