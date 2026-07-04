"""Stage 5: judge candidate frames with a vision LLM (Claude).

Requires ANTHROPIC_API_KEY in the environment (see .env.example).

This local script calls the synchronous Messages API one batch at a time
(simplest for testing a handful of frames). The full pipeline should switch
to the Message Batches API for the ~20-50 batches/video a real run produces,
per the plan's cost design.
"""

import argparse
import base64
import json
import os
import sys
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

load_dotenv()

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


def encode_image(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    if max(img.size) > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def transcript_context(segments: list[dict], timestamp: float) -> str:
    window = [
        s for s in segments
        if s["end_ts"] >= timestamp - CONTEXT_WINDOW_SECONDS and s["start_ts"] <= timestamp + CONTEXT_WINDOW_SECONDS
    ]
    return "\n".join(f"[{s['start_ts']:.0f}s] {s['speaker']}: {s['text']}" for s in window)


def judge_batch(client, batch: list[dict], transcript_segments: list[dict]) -> list[dict]:
    content = []
    for i, frame in enumerate(batch, start=1):
        context = transcript_context(transcript_segments, frame["timestamp"]) if transcript_segments else "(no transcript available)"
        content.append({"type": "text", "text": f"Frame {i} (t={frame['timestamp']:.1f}s). Transcript context:\n{context}"})
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": encode_image(Path(frame["path"]))},
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
        print(
            "ANTHROPIC_API_KEY is not set. Get one at https://console.anthropic.com/, "
            "add it to local_test/.env, then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    accepted = []

    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start:start + BATCH_SIZE]
        judgments = judge_batch(client, batch, transcript_segments)
        for j in judgments:
            frame = batch[j["frame_index"] - 1]
            if j["include"]:
                accepted.append({**frame, **j})
        print(f"Batch {start // BATCH_SIZE + 1}: {len(judgments)} judged, {sum(1 for j in judgments if j['include'])} accepted")

    return accepted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates_json", type=Path)
    parser.add_argument("--transcript", type=Path, default=Path("output/transcript.json"))
    parser.add_argument("--output", type=Path, default=Path("output/accepted_frames.json"))
    args = parser.parse_args()

    candidates = json.loads(args.candidates_json.read_text())
    transcript_segments = json.loads(args.transcript.read_text())["segments"] if args.transcript.exists() else []

    accepted = judge_frames(candidates, transcript_segments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(accepted, indent=2))
    print(f"\n{len(accepted)}/{len(candidates)} candidates accepted. Written to {args.output}")
