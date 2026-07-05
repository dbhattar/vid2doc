"""Classify candidate frames with a vision LLM: content type, caption, and
(for tables) extracted structured data. Frames classified "filler" are dropped.

Two providers, same pattern as the other LLM stages: anthropic (default,
tool use) or openai (Chat Completions structured outputs, strict JSON schema).
"""

import base64
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

from ..config import settings
from ..exceptions import PipelineError

BATCH_SIZE = 8
MAX_LONG_EDGE = 1568

SYSTEM_PROMPT = """You are classifying video frames for inclusion in a document generated from a video transcript.

For each frame, decide:
- "filler" if it's just a person's face/webcam view, a blank/transition frame, or a near-duplicate of content already covered -- these are dropped from the document.
- "table" if it shows tabular data with rows/columns -- also extract the table's headers and rows as structured data, best effort from what's visible.
- Otherwise pick the content type that best fits: slide, diagram, whiteboard, code, photo, or chart.

Always include a one-sentence present-tense caption describing what's shown (empty string for filler frames)."""

TABLE_SCHEMA_ANTHROPIC = {
    "type": ["object", "null"],
    "properties": {
        "headers": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
    },
    "required": ["headers", "rows"],
}

ITEM_SCHEMA_ANTHROPIC = {
    "type": "object",
    "properties": {
        "frame_index": {"type": "integer", "description": "1-based index within this batch"},
        "content_type": {
            "type": "string",
            "enum": ["slide", "diagram", "whiteboard", "code", "photo", "chart", "table", "filler"],
        },
        "caption": {"type": "string"},
        "table": TABLE_SCHEMA_ANTHROPIC,
    },
    "required": ["frame_index", "content_type", "caption", "table"],
}

CLASSIFY_TOOL = {
    "name": "submit_classifications",
    "description": "Submit content-type classifications for a batch of video frames.",
    "input_schema": {
        "type": "object",
        "properties": {"classifications": {"type": "array", "items": ITEM_SCHEMA_ANTHROPIC}},
        "required": ["classifications"],
    },
}

# OpenAI strict structured outputs require additionalProperties: false at every
# object level, and nullable fields as an explicit {"anyOf": [schema, {"type": "null"}]}.
CLASSIFY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frame_index": {"type": "integer"},
                    "content_type": {
                        "type": "string",
                        "enum": ["slide", "diagram", "whiteboard", "code", "photo", "chart", "table", "filler"],
                    },
                    "caption": {"type": "string"},
                    "table": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "headers": {"type": "array", "items": {"type": "string"}},
                                    "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                                },
                                "required": ["headers", "rows"],
                                "additionalProperties": False,
                            },
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["frame_index", "content_type", "caption", "table"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["classifications"],
    "additionalProperties": False,
}


def _encode_image(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    if max(img.size) > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _classify_batch_anthropic(client, batch: list[dict]) -> list[dict]:
    content = []
    for i, frame in enumerate(batch, start=1):
        content.append({"type": "text", "text": f"Frame {i} (t={frame['timestamp']:.1f}s)"})
        content.append(
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode_image(Path(frame["path"]))}}
        )

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "submit_classifications"},
        messages=[{"role": "user", "content": content}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input["classifications"]
    return []


def _classify_batch_openai(client, batch: list[dict]) -> list[dict]:
    import json

    content = []
    for i, frame in enumerate(batch, start=1):
        content.append({"type": "text", "text": f"Frame {i} (t={frame['timestamp']:.1f}s)"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(Path(frame['path']))}"}})

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "submit_classifications", "strict": True, "schema": CLASSIFY_JSON_SCHEMA},
        },
    )
    return json.loads(response.choices[0].message.content)["classifications"]


def classify_frames(candidates: list[dict], provider: str | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (images_meta, tables_meta), each item tagged with a unique
    sequential "id" used later to reference it from the composed document plan."""
    provider = provider or settings.LLM_PROVIDER

    if provider == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PipelineError("OPENAI_API_KEY is not set")
        client = openai.OpenAI(api_key=api_key)
        classify_batch = _classify_batch_openai
    else:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise PipelineError("ANTHROPIC_API_KEY is not set")
        client = anthropic.Anthropic(api_key=api_key)
        classify_batch = _classify_batch_anthropic

    images_meta: list[dict] = []
    tables_meta: list[dict] = []
    next_id = 1

    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start:start + BATCH_SIZE]
        for c in classify_batch(client, batch):
            frame = batch[c["frame_index"] - 1]
            if c["content_type"] == "filler":
                continue
            if c["content_type"] == "table" and c.get("table"):
                tables_meta.append({
                    "id": next_id,
                    "kind": "table",
                    "timestamp": frame["timestamp"],
                    "caption": c["caption"],
                    "headers": c["table"]["headers"],
                    "rows": c["table"]["rows"],
                })
            else:
                images_meta.append({
                    "id": next_id,
                    "kind": "image",
                    "timestamp": frame["timestamp"],
                    "caption": c["caption"],
                    "content_type": c["content_type"],
                    "path": frame["path"],
                })
            next_id += 1

    return images_meta, tables_meta
