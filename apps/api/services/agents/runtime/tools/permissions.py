# apps/api/services/agents/runtime/tools/permissions.py

"""Workspace-aware runtime tool availability checks."""

from services.agents.runtime.tools.contract import RuntimeToolDefinition


def is_tool_allowed(
    definition: RuntimeToolDefinition,
    *,
    workspace: object | None,
    agent: object | None = None,
) -> bool:
    """Return whether a runtime tool is available in this context."""
    return True
