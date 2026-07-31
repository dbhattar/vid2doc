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

SYSTEM_PROMPT = """You are classifying video frames for inclusion in a document generated from a video transcript. The transcript already has everything anyone said, so a frame only earns a spot if its visual adds information the transcript doesn't -- a diagram, chart, table, code, whiteboard, or a slide with real structured content.

Classify a frame as "filler" (dropped from the document) if ANY of these apply:
- The main subject is a person -- a presenter, speaker, or webcam view -- even while gesturing, standing next to a whiteboard, or only partially in frame. Only classify as non-filler if the frame's main subject is the informational content itself, not a person showing or discussing it.
- It's a dense wall of unstructured text (e.g. a paragraph or article being read on screen) rather than a genuine structured slide, code block, diagram, or table -- this doesn't add anything the transcript doesn't already say.
- It's unrelated to what's being discussed at that point in the video -- background/decorative footage, B-roll, or a cutaway.
- It's a blank/transition frame, or a near-duplicate of content already covered.

For everything else, decide:
- "table" if it shows tabular data with rows/columns -- also extract the table's headers and rows as structured data, best effort from what's visible.
- Otherwise pick the content type that best fits: slide, diagram, whiteboard, code, photo, or chart."""

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
        "table": TABLE_SCHEMA_ANTHROPIC,
    },
    "required": ["frame_index", "content_type", "table"],
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
                "required": ["frame_index", "content_type", "table"],
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
                    "headers": c["table"]["headers"],
                    "rows": c["table"]["rows"],
                    # Kept (unlike before) so a table item can still be viewed/saved
                    # as an image during frame review, same as any other item.
                    "path": frame["path"],
                })
            else:
                images_meta.append({
                    "id": next_id,
                    "kind": "image",
                    "timestamp": frame["timestamp"],
                    "content_type": c["content_type"],
                    "path": frame["path"],
                })
            next_id += 1

    return images_meta, tables_meta


CAPTION_SYSTEM_PROMPT = """You are writing a one-sentence, present-tense caption for a frame that a user has already chosen to include in a document generated from a video transcript.

State plainly what the frame's content actually is or says -- lead with the substance, not the medium. For example, write "Q3 revenue grew 12% year over year" rather than "A slide showing Q3 revenue growth", and "Recursive binary search implementation in Python" rather than "A code snippet of a binary search function". For a table, describe what its data represents rather than restating its headers."""

CAPTION_ITEM_SCHEMA_ANTHROPIC = {
    "type": "object",
    "properties": {
        "frame_index": {"type": "integer", "description": "1-based index within this batch"},
        "caption": {"type": "string"},
    },
    "required": ["frame_index", "caption"],
}

CAPTION_TOOL = {
    "name": "submit_captions",
    "description": "Submit captions for a batch of already-selected video frames.",
    "input_schema": {
        "type": "object",
        "properties": {"captions": {"type": "array", "items": CAPTION_ITEM_SCHEMA_ANTHROPIC}},
        "required": ["captions"],
    },
}

CAPTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "captions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"frame_index": {"type": "integer"}, "caption": {"type": "string"}},
                "required": ["frame_index", "caption"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["captions"],
    "additionalProperties": False,
}


def _caption_batch_anthropic(client, batch: list[dict]) -> list[dict]:
    content = []
    for i, item in enumerate(batch, start=1):
        label = "table" if item["kind"] == "table" else item.get("content_type", "image")
        content.append({"type": "text", "text": f"Frame {i} ({label})"})
        content.append(
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _encode_image(Path(item["path"]))}}
        )

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        system=CAPTION_SYSTEM_PROMPT,
        tools=[CAPTION_TOOL],
        tool_choice={"type": "tool", "name": "submit_captions"},
        messages=[{"role": "user", "content": content}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input["captions"]
    return []


def _caption_batch_openai(client, batch: list[dict]) -> list[dict]:
    import json

    content = []
    for i, item in enumerate(batch, start=1):
        label = "table" if item["kind"] == "table" else item.get("content_type", "image")
        content.append({"type": "text", "text": f"Frame {i} ({label})"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(Path(item['path']))}"}})

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": CAPTION_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "submit_captions", "strict": True, "schema": CAPTION_JSON_SCHEMA},
        },
    )
    return json.loads(response.choices[0].message.content)["captions"]


def caption_frames(items: list[dict], provider: str | None = None) -> list[dict]:
    """Generates a caption for each item, given only the ones the user chose
    to keep during frame review -- run after that decision (see
    pipeline.resume_after_review), not during classify_frames, so
    caption-writing (and its vision-LLM cost) is never spent on a frame the
    user ends up skipping. Returns copies of `items` with "caption" filled
    in; order and all other fields are preserved."""
    if not items:
        return []

    provider = provider or settings.LLM_PROVIDER

    if provider == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PipelineError("OPENAI_API_KEY is not set")
        client = openai.OpenAI(api_key=api_key)
        caption_batch = _caption_batch_openai
    else:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise PipelineError("ANTHROPIC_API_KEY is not set")
        client = anthropic.Anthropic(api_key=api_key)
        caption_batch = _caption_batch_anthropic

    captioned: list[dict] = []
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        for c in caption_batch(client, batch):
            item = batch[c["frame_index"] - 1]
            captioned.append({**item, "caption": c["caption"]})
    return captioned
