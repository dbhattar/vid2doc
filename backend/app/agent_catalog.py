"""Pre-made skill catalog and the catalog API for AI agents (see agents.py).
Users only pick ids from here, so adding a skill or tool is a code change, not
a migration. Skills are named system-prompt snippets defined below; tools are
auto-discovered modules in app/agent_tools/ (see its __init__.py).
"""

from .agent_tools import TOOLS

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

def catalog(user: dict) -> dict:
    """What the frontend shows in the create/edit form. A tool that can't be
    used by this user right now (e.g. Drive not connected) is still listed,
    with the reason."""
    tools = []
    for tool_id, tool in TOOLS.items():
        check = tool.get("available")
        reason = check(user) if check else None
        tools.append(
            {
                "id": tool_id,
                "name": tool["name"],
                "description": tool["description"],
                "available": reason is None,
                "unavailable_reason": reason,
            }
        )
    return {
        "tools": tools,
        "skills": [{"id": k, "name": v["name"], "description": v["description"]} for k, v in SKILLS.items()],
    }


def unavailable_reason(tool_id: str, user: dict) -> str | None:
    check = TOOLS[tool_id].get("available")
    return check(user) if check else None


def is_valid_tool(tool_id: str) -> bool:
    return tool_id in TOOLS


def is_valid_skill(skill_id: str) -> bool:
    return skill_id in SKILLS
