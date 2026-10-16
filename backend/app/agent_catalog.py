"""Pre-made tool and skill catalog for AI agents (see agents.py). Both are
plain in-code dicts, not DB rows -- users only pick ids from here, so adding
a tool or skill is a code change, not a migration. This is the proof-of-
concept catalog; user-defined tools/skills are a later phase.

Skills are named system-prompt snippets. Tools are OpenAI function tools
(`schema`) plus a `run(ctx, args)` callable returning a string for the model,
except the built-in `web_search`, which OpenAI runs server-side (`builtin`).

`ctx` is {"documents": [{"id", "title", "content"}, ...], "client": openai
client} -- built per request by agents.run_agent.
"""

import re

from .config import settings

SKILLS: dict[str, dict] = {
    "meeting_summarizer": {
        "name": "Meeting summarizer",
        "description": "Summarizes meetings into decisions, action items with owners, and open questions.",
        "prompt": (
            "When asked to summarize a meeting or discussion, structure the answer as: "
            "1) Key decisions, 2) Action items (each with an owner and due date if mentioned), "
            "3) Open questions. Be concise and only include what the documents actually support."
        ),
    },
    "study_guide": {
        "name": "Study guide & quiz",
        "description": "Turns documents into key concepts, plain-language explanations, and quiz questions.",
        "prompt": (
            "When asked to help study or learn, produce: key concepts with one-sentence explanations, "
            "then a short quiz (mix of multiple choice and short answer) with an answer key at the end. "
            "Base everything on the attached documents."
        ),
    },
}

SEARCH_RESULT_LIMIT = 5
SNIPPET_CHARS = 600
READ_CHUNK_CHARS = 12000


def _paragraphs(content: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]


def _search_documents(ctx: dict, args: dict) -> str:
    query = str(args.get("query", "")).lower()
    terms = [t for t in re.findall(r"\w+", query) if len(t) > 2]
    if not terms:
        return "Provide a query with at least one meaningful word."
    scored = []
    for doc in ctx["documents"]:
        for para in _paragraphs(doc["content"]):
            lower = para.lower()
            score = sum(lower.count(t) for t in terms)
            if score:
                scored.append((score, doc, para))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return "No matches in the attached documents."
    return "\n\n".join(
        f'[document_id={doc["id"]} title="{doc["title"]}"]\n{para[:SNIPPET_CHARS]}'
        for _, doc, para in scored[:SEARCH_RESULT_LIMIT]
    )


def _read_document(ctx: dict, args: dict) -> str:
    doc = next((d for d in ctx["documents"] if d["id"] == args.get("document_id")), None)
    if not doc:
        return "No attached document with that document_id."
    offset = max(int(args.get("offset") or 0), 0)
    chunk = doc["content"][offset : offset + READ_CHUNK_CHARS]
    remaining = len(doc["content"]) - offset - len(chunk)
    suffix = f"\n\n[{remaining} more characters -- call again with offset={offset + len(chunk)}]" if remaining > 0 else ""
    return (chunk or "(end of document)") + suffix


def _research_topic(ctx: dict, args: dict) -> str:
    topic = str(args.get("topic", "")).strip()
    if not topic:
        return "Provide a topic."
    excerpts = _search_documents(ctx, {"query": topic})
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


TOOLS: dict[str, dict] = {
    "search_documents": {
        "name": "Search documents",
        "description": "Search and read the agent's attached documents (the knowledge base).",
        "functions": [
            {
                "type": "function",
                "name": "search_documents",
                "description": "Keyword search across the attached documents. Returns the best-matching passages with their document_id and title.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "strict": True,
                "run": _search_documents,
            },
            {
                "type": "function",
                "name": "read_document",
                "description": "Read an attached document by document_id, in chunks. Pass offset to continue a long document.",
                "parameters": {
                    "type": "object",
                    "properties": {"document_id": {"type": "string"}, "offset": {"type": ["integer", "null"]}},
                    "required": ["document_id", "offset"],
                    "additionalProperties": False,
                },
                "strict": True,
                "run": _read_document,
            },
        ],
    },
    "web_search": {
        "name": "Web search",
        "description": "Look things up on the web for current information.",
        "builtin": {"type": "web_search"},
    },
    "research_topic": {
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
                "run": _research_topic,
            },
        ],
    },
}


def catalog() -> dict:
    """What the frontend shows in the create/edit form."""
    return {
        "tools": [{"id": k, "name": v["name"], "description": v["description"]} for k, v in TOOLS.items()],
        "skills": [{"id": k, "name": v["name"], "description": v["description"]} for k, v in SKILLS.items()],
    }


def is_valid_tool(tool_id: str) -> bool:
    return tool_id in TOOLS


def is_valid_skill(skill_id: str) -> bool:
    return skill_id in SKILLS
