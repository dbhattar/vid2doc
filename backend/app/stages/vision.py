"""Judge candidate frames with a vision LLM (Claude). Requires ANTHROPIC_API_KEY."""

import base64
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

from ..exceptions import PipelineError

BATCH_SIZE = 8
MAX_LONG_EDGE = 1568
CONTEXT_WINDOW_SECONDS = 30

SYSTEM_PROMPT = """You are judging video frames for inclusion in a document generated from a video transcript.

Include a frame only if it shows meaningful, distinct visual content: a slide, a diagram, code, a whiteboard, a chart, or a photo relevant to what's being discussed. Reject frames that are just a person's face/webcam view, a blank or mostly-empty transition, or a near-duplicate of content already likely covered by a nearby frame.

For each frame, return: whether to include it, your confidence (0-1), a one-sentence present-tense caption, its content type, and a short quote from the provided transcript context that best anchors where this frame belongs (empty string if no good anchor)."""

JUDGE_TOOL = {
    "name": "submit_judgments",
    "description": "Submit relevance judgments for a batch of video frames.",
    "input_schema": {
        "type": "object",
        "properties": {
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "frame_index": {"type": "integer", "description": "1-based index within this batch"},
                        "include": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "caption": {"type": "string"},
                        "content_type": {
                            "type": "string",
                            "enum": ["slide", "diagram", "whiteboard", "code", "photo", "chart", "other"],
                        },
                        "placement_anchor": {"type": "string"},
                    },
                    "required": ["frame_index", "include", "confidence", "caption", "content_type", "placement_anchor"],
                },
            }
        },
        "required": ["judgments"],
    },
}


def _encode_image(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    if max(img.size) > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _transcript_context(segments: list[dict], timestamp: float) -> str:
    window = [
        s for s in segments
        if s["end_ts"] >= timestamp - CONTEXT_WINDOW_SECONDS and s["start_ts"] <= timestamp + CONTEXT_WINDOW_SECONDS
    ]
    return "\n".join(f"[{s['start_ts']:.0f}s] {s['speaker']}: {s['text']}" for s in window)


def _judge_batch(client, batch: list[dict], transcript_segments: list[dict]) -> list[dict]:
    content = []
    for i, frame in enumerate(batch, start=1):
        context = _transcript_context(transcript_segments, frame["timestamp"]) if transcript_segments else "(no transcript available)"
        content.append({"type": "text", "text": f"Frame {i} (t={frame['timestamp']:.1f}s). Transcript context:\n{context}"})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode_image(Path(frame["path"]))},
            }
        )

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "submit_judgments"},
        messages=[{"role": "user", "content": content}],
    )

    for block in response.content:
        if block.type == "tool_use":
            return block.input["judgments"]
    return []


def judge_frames(candidates: list[dict], transcript_segments: list[dict]) -> list[dict]:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PipelineError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)
    accepted = []

    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start:start + BATCH_SIZE]
        judgments = _judge_batch(client, batch, transcript_segments)
        for j in judgments:
            frame = batch[j["frame_index"] - 1]
            if j["include"]:
                accepted.append({**frame, **j})

    return accepted
