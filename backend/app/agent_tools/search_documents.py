import re

SEARCH_RESULT_LIMIT = 5
SNIPPET_CHARS = 600
READ_CHUNK_CHARS = 12000


def _paragraphs(content: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]


def search(ctx: dict, args: dict) -> str:
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


def read(ctx: dict, args: dict) -> str:
    doc = next((d for d in ctx["documents"] if d["id"] == args.get("document_id")), None)
    if not doc:
        return "No attached document with that document_id."
    offset = max(int(args.get("offset") or 0), 0)
    chunk = doc["content"][offset : offset + READ_CHUNK_CHARS]
    remaining = len(doc["content"]) - offset - len(chunk)
    suffix = f"\n\n[{remaining} more characters -- call again with offset={offset + len(chunk)}]" if remaining > 0 else ""
    return (chunk or "(end of document)") + suffix


TOOL = {
    "order": 10,
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
            "run": search,
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
            "run": read,
        },
    ],
}
