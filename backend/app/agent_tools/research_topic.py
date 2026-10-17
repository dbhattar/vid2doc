from ..config import settings
from . import search_documents


def run(ctx: dict, args: dict) -> str:
    topic = str(args.get("topic", "")).strip()
    if not topic:
        return "Provide a topic."
    excerpts = search_documents.search(ctx, {"query": topic})
    response = ctx["client"].responses.create(
        model=settings.AGENT_OPENAI_MODEL,
        tools=[{"type": "web_search"}],
        instructions=(
            "You research a topic that came up in the user's own documents. Use web search to write a short, "
            "factual background note (a short paragraph plus up to 3 bullet points) that goes beyond what the "
            "excerpts say, and end with source links. Don't repeat the excerpts back."
        ),
        input=f"Topic: {topic}\n\nRelevant excerpts from the user's documents:\n{excerpts}",
    )
    return response.output_text


TOOL = {
    "order": 30,
    "name": "Research a topic",
    "description": "Research a topic from your documents on the web and return a sourced background note.",
    "functions": [
        {
            "type": "function",
            "name": "research_topic",
            "description": "Research a topic that appears in the user's documents using web search; returns a sourced background note.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
                "additionalProperties": False,
            },
            "strict": True,
            "run": run,
        },
    ],
}
