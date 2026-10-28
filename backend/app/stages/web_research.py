"""Batch web research for the "notes" and "research" transformations (see
stages/transform.py). The non-interactive twin of agent_tools/research_topic.py
and live_research.py: OpenAI's Responses API with the built-in `web_search`
tool. OpenAI-only, like those -- web search isn't something LLM_PROVIDER
switches between providers."""

import os

from ..agents import collect_sources, strip_citation_markers
from ..config import settings
from ..exceptions import PipelineError

RESEARCH_INSTRUCTIONS = (
    "You research one topic that came up in a video. Use web search to write a short, factual background "
    "section (a short paragraph plus up to 3 bullet points) that goes beyond what the video says. Be "
    "specific and accurate, and don't repeat the video's own wording back."
)


def available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def research_topic(topic: str, context: str) -> dict:
    """Returns {"summary": str, "links": [{"title", "url"}]} -- links are the
    pages web search actually cited, deduplicated by URL."""
    import openai

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise PipelineError("OPENAI_API_KEY is not set")
    response = openai.OpenAI(api_key=api_key).responses.create(
        model=settings.AGENT_OPENAI_MODEL,
        tools=[{"type": "web_search"}],
        instructions=RESEARCH_INSTRUCTIONS,
        input=f"Topic: {topic}\n\nWhat the video says about it:\n{context}",
    )
    links: dict[str, dict] = {}
    for source in collect_sources(response):
        links.setdefault(source["url"], source)
    return {"summary": strip_citation_markers(response.output_text).strip(), "links": list(links.values())}
