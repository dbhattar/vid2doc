"""Generate a short on-screen "highlight" headline per scene (job_type ==
"video_gen") -- one batched LLM call covering every scene (typically well
under 30 scenes, comfortably fits in one prompt) rather than one call per
scene, since headlines must exist before the awaiting_review pause (the user
reviews/edits them there) and a single batched call is both cheaper and
faster than N small ones.
"""

import os

from ..config import settings
from ..exceptions import PipelineError

SYSTEM_PROMPT = """You are writing short on-screen headline text for each scene of a generated video, given its underlying transcript.

For each scene (identified by id), write ONE short, punchy on-screen phrase (roughly 3-8 words, no trailing punctuation) capturing the core point of that scene -- like a video's on-screen title/lower-third, not a verbatim quote from the transcript."""

HEADLINE_SCHEMA = {
    "type": "object",
    "properties": {"id": {"type": "integer"}, "headline": {"type": "string"}},
    "required": ["id", "headline"],
}

HIGHLIGHT_TOOL = {
    "name": "submit_headlines",
    "description": "Submit the on-screen headline for each scene.",
    "input_schema": {
        "type": "object",
        "properties": {"headlines": {"type": "array", "items": HEADLINE_SCHEMA}},
        "required": ["headlines"],
    },
}

HIGHLIGHT_JSON_SCHEMA = {
    "type": "object",
    "properties": {"headlines": {"type": "array", "items": {**HEADLINE_SCHEMA, "additionalProperties": False}}},
    "required": ["headlines"],
    "additionalProperties": False,
}


def _scene_text(scene: dict, segments: list[dict]) -> str:
    return " ".join(
        s["text"] for s in segments if s["start_ts"] >= scene["start_ts"] and s["end_ts"] <= scene["end_ts"]
    )


def _user_content(scenes: list[dict], segments: list[dict]) -> str:
    return "\n\n".join(f"id={s['id']}: {_scene_text(s, segments)}" for s in scenes)


def _generate_anthropic(client, scenes: list[dict], segments: list[dict]) -> dict[int, str]:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[HIGHLIGHT_TOOL],
        tool_choice={"type": "tool", "name": "submit_headlines"},
        messages=[{"role": "user", "content": _user_content(scenes, segments)}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return {h["id"]: h["headline"] for h in block.input["headlines"]}
    return {}


def _generate_openai(client, scenes: list[dict], segments: list[dict]) -> dict[int, str]:
    import json

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(scenes, segments)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "submit_headlines", "strict": True, "schema": HIGHLIGHT_JSON_SCHEMA},
        },
    )
    headlines = json.loads(response.choices[0].message.content)["headlines"]
    return {h["id"]: h["headline"] for h in headlines}


def _get_client_and_fn(provider: str):
    if provider == "openai":
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PipelineError("OPENAI_API_KEY is not set")
        return openai.OpenAI(api_key=api_key), _generate_openai
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PipelineError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key), _generate_anthropic


def generate_headlines(scenes: list[dict], segments: list[dict], provider: str | None = None) -> list[dict]:
    """Returns `scenes` with a "headline" key added to each -- falls back to
    each scene's own `title` (set by segment_scenes) if the LLM call fails,
    so a headline-generation hiccup never blocks the job."""
    if not scenes:
        return scenes

    provider = provider or settings.LLM_PROVIDER
    try:
        client, generate = _get_client_and_fn(provider)
        headlines = generate(client, scenes, segments)
    except Exception:
        headlines = {}

    for scene in scenes:
        scene["headline"] = headlines.get(scene["id"]) or scene["title"]
    return scenes
