# OpenAI runs this one server-side (Responses API built-in tool), so there's no `run`.
TOOL = {
    "order": 20,
    "name": "Web search",
    "description": "Look things up on the web for current information.",
    "builtin": {"type": "web_search"},
}
