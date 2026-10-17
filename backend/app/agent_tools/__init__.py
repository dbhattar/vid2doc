"""Auto-discovered catalog of tools an AI agent can use (see ../agents.py).

To add a tool: create a module here (e.g. `my_tool.py`) that defines a
module-level `TOOL` dict -- nothing else to register. The module's file name
is the tool id stored on agents (`agents.tool_ids`), so never rename a
shipped one. Modules starting with "_" are helpers, not tools. See "Adding
an agent tool" in backend/README.md for the full shape.
"""

import importlib
import pkgutil

TOOLS: dict[str, dict] = {}


def _discover() -> None:
    found = []
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        found.append((module.TOOL.get("order", 100), module_info.name, module.TOOL))
    for _, tool_id, tool in sorted(found, key=lambda t: (t[0], t[1])):
        TOOLS[tool_id] = tool


_discover()
