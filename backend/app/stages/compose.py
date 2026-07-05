"""Compose the transcript + classified visuals into a structured, topic-organized
document plan -- the LLM writes real prose here, not a mechanical transcript stitch.

Non-overlapping sliding windows over the transcript (~3500 words each) keep this
scalable to arbitrarily long videos at roughly constant cost per minute of audio.
Each window gets its transcript slice plus the images/tables whose timestamps
fall inside it, and returns one or more sections (heading + ordered content
blocks) covering that slice. Windows are concatenated in order to form the
final section list -- no overlap/dedup needed since each window produces a
self-contained, non-duplicated slice of the document (unlike naive "find topic
boundaries" segmentation, which needs boundary reconciliation across windows).
"""

import os

from ..config import settings
from ..exceptions import PipelineError

WINDOW_WORDS = 3500

SYSTEM_PROMPT = """You are writing a clear, organized document from a slice of a video's transcript.

You're given the transcript for this slice (with speaker labels and timestamps) and a list of images/tables extracted from the video during this same time range, each with an id, timestamp, and description.

Write one or more sections covering this transcript slice. Each section has a short heading and a list of content blocks in reading order:
- paragraph blocks: rewritten, coherent prose synthesizing what was said. Do not copy transcript fragments verbatim -- write it as you would in a real document, in your own words, preserving the actual information and meaning.
- image/table blocks: reference only ids from the provided list, placed wherever they topically belong (not necessarily in timestamp order).

Use every provided image/table id at least once, in whichever section it best supports. Never invent an id that wasn't provided.

For each block, always fill in all four fields even if unused: use "text" for paragraph content (empty string for image/table blocks), and "ref"/"caption" for image/table blocks (ref=0 and caption="" for paragraph blocks)."""

TITLE_SYSTEM_PROMPT = "Given section headings from a document generated from a video, write one concise, specific title for the whole document (a few words, no quotes, no trailing punctuation)."

BLOCK_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["paragraph", "image", "table"]},
        "text": {"type": "string"},
        "ref": {"type": "integer"},
        "caption": {"type": "string"},
    },
    "required": ["type", "text", "ref", "caption"],
}

SECTION_SCHEMA_ANTHROPIC = {
    "type": "object",
    "properties": {
        "heading": {"type": "string"},
        "blocks": {"type": "array", "items": BLOCK_SCHEMA},
    },
    "required": ["heading", "blocks"],
}

COMPOSE_TOOL = {
    "name": "submit_sections",
    "description": "Submit the composed sections for this transcript window.",
    "input_schema": {
        "type": "object",
        "properties": {"sections": {"type": "array", "items": SECTION_SCHEMA_ANTHROPIC}},
        "required": ["sections"],
    },
}

COMPOSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "blocks": {"type": "array", "items": {**BLOCK_SCHEMA, "additionalProperties": False}},
                },
                "required": ["heading", "blocks"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sections"],
    "additionalProperties": False,
}

TITLE_TOOL = {
    "name": "submit_title",
    "description": "Submit the document title.",
    "input_schema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
}

TITLE_JSON_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}


def _make_windows(segments: list[dict]) -> list[list[dict]]:
    windows = []
    i = 0
    while i < len(segments):
        window, word_count = [], 0
        j = i
        while j < len(segments) and word_count < WINDOW_WORDS:
            window.append(segments[j])
            word_count += len(segments[j]["text"].split())
            j += 1
        windows.append(window)
        i = j
    return windows


def _assign_visuals_to_windows(windows: list[list[dict]], visuals: list[dict]) -> list[list[dict]]:
    assigned: list[list[dict]] = [[] for _ in windows]
    for v in visuals:
        placed = False
        for i, window in enumerate(windows):
            if window[0]["start_ts"] <= v["timestamp"] <= window[-1]["end_ts"]:
                assigned[i].append(v)
                placed = True
                break
        if not placed and windows:
            distances = [
                min(abs(w[0]["start_ts"] - v["timestamp"]), abs(w[-1]["end_ts"] - v["timestamp"]))
                for w in windows
            ]
            assigned[distances.index(min(distances))].append(v)
    return assigned


def _window_text(window: list[dict]) -> str:
    return "\n".join(f"[{s['start_ts']:.0f}s] {s['speaker']}: {s['text']}" for s in window)


def _visuals_text(visuals: list[dict]) -> str:
    if not visuals:
        return "(none)"
    return "\n".join(f"id={v['id']} kind={v['kind']} t={v['timestamp']:.1f}s: {v['caption']}" for v in visuals)


def _user_content(window: list[dict], visuals: list[dict]) -> str:
    return f"TRANSCRIPT:\n{_window_text(window)}\n\nAVAILABLE IMAGES/TABLES:\n{_visuals_text(visuals)}"


def _compose_window_anthropic(client, window: list[dict], visuals: list[dict]) -> list[dict]:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[COMPOSE_TOOL],
        tool_choice={"type": "tool", "name": "submit_sections"},
        messages=[{"role": "user", "content": _user_content(window, visuals)}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input["sections"]
    return []


def _compose_window_openai(client, window: list[dict], visuals: list[dict]) -> list[dict]:
    import json

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(window, visuals)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "submit_sections", "strict": True, "schema": COMPOSE_JSON_SCHEMA},
        },
    )
    return json.loads(response.choices[0].message.content)["sections"]


def _get_client_and_fns(provider: str):
    if provider == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PipelineError("OPENAI_API_KEY is not set")
        return openai.OpenAI(api_key=api_key), _compose_window_openai, _generate_title_openai
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PipelineError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key), _compose_window_anthropic, _generate_title_anthropic


def compose_document(segments: list[dict], visuals: list[dict], provider: str | None = None) -> list[dict]:
    provider = provider or settings.LLM_PROVIDER
    client, compose_window, _ = _get_client_and_fns(provider)

    windows = _make_windows(segments)
    visuals_by_window = _assign_visuals_to_windows(windows, visuals)

    all_sections: list[dict] = []
    for window, window_visuals in zip(windows, visuals_by_window):
        all_sections.extend(compose_window(client, window, window_visuals))
    return all_sections


def _generate_title_anthropic(client, headings: list[str]) -> str:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=100,
        system=TITLE_SYSTEM_PROMPT,
        tools=[TITLE_TOOL],
        tool_choice={"type": "tool", "name": "submit_title"},
        messages=[{"role": "user", "content": "\n".join(headings)}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input["title"]
    return headings[0] if headings else "Video Document"


def _generate_title_openai(client, headings: list[str]) -> str:
    import json

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": TITLE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(headings)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "submit_title", "strict": True, "schema": TITLE_JSON_SCHEMA},
        },
    )
    return json.loads(response.choices[0].message.content)["title"]


def generate_title(sections: list[dict], provider: str | None = None) -> str:
    if not sections:
        return "Video Document"
    headings = [s["heading"] for s in sections]
    provider = provider or settings.LLM_PROVIDER
    try:
        client, _, generate = _get_client_and_fns(provider)
        return generate(client, headings)
    except Exception:
        return headings[0]
