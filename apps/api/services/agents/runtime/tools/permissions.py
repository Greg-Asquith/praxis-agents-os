# apps/api/services/agents/runtime/tools/permissions.py

"""Workspace-aware runtime tool availability checks."""

from services.agents.runtime.tools.contract import RuntimeToolDefinition


def is_tool_allowed(
    definition: RuntimeToolDefinition,
    *,
    workspace: object | None,
    agent: object | None = None,
    disabled_tool_names: frozenset[str] = frozenset(),
) -> bool:
    """Return whether a runtime tool is available in this context."""
    if workspace is not None and definition.name in disabled_tool_names:
        return False
    return definition.availability_check is None or definition.availability_check()
