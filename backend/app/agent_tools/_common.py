"""Helpers shared by agent tool modules."""

import time

# Context handed to every tool's `run(ctx, args)` by agents.run_agent:
#   {"documents": [{"id", "title", "content"}], "client": openai client, "user": user dict}

_rate_log: dict[tuple[str, str], list[float]] = {}


def rate_limited(tool_id: str, user_id: str, max_calls: int, window_seconds: int = 3600) -> bool:
    """True (and doesn't record a call) if this user already used the tool
    `max_calls` times in the window; otherwise records the call and returns
    False. In-process only -- same trade-off as agents.check_rate_limit."""
    now = time.monotonic()
    key = (tool_id, user_id)
    recent = [t for t in _rate_log.get(key, []) if t >= now - window_seconds]
    if len(recent) >= max_calls:
        _rate_log[key] = recent
        return True
    recent.append(now)
    _rate_log[key] = recent
    return False


def wrap_untrusted(text: str, source: str) -> str:
    """Marks text from outside Framewrite (web pages, ...) as data. The agent's
    system prompt tells the model never to follow instructions found in tool
    results; the delimiter just makes the boundary explicit. Any closing tag
    inside the content is defused so it can't end the block early."""
    safe = text.replace("</untrusted_content>", "[/untrusted_content]")
    return f'<untrusted_content source="{source}">\n{safe}\n</untrusted_content>'
