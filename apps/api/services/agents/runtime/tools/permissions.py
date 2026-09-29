# apps/api/services/agents/runtime/tools/permissions.py

"""Workspace-aware runtime tool availability and policy checks."""

from collections.abc import Mapping

from services.agents.runtime.tools.contract import RuntimeToolDefinition, ToolPolicy


def is_tool_allowed(
    definition: RuntimeToolDefinition,
    *,
    workspace: object | None,
    agent: object | None = None,
    disabled_tool_names: frozenset[str] = frozenset(),
) -> bool:
    """Return whether a runtime tool is available in this context."""
    if definition.always_allowed_when_mounted:
        return True
    if workspace is not None and definition.name in disabled_tool_names:
        return False
    return definition.availability_check is None or definition.availability_check()


def resolve_tool_policy(
    definition: RuntimeToolDefinition,
    *,
    agent_policies: Mapping[str, str],
    workspace_policies: Mapping[str, str],
) -> ToolPolicy:
    """Resolve the agent override, then the workspace default, then the tool's default."""
    if definition.auto_mount:
        return definition.default_policy
    allowed_policies = definition.allowed_policies()
    for candidate in (
        agent_policies.get(definition.name),
        workspace_policies.get(definition.name),
    ):
        # An unsupported saved value never loosens the tool; fall through instead.
        if candidate in allowed_policies:
            return candidate
    return definition.default_policy
