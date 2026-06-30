# apps/api/service/agents/runtime/tools/registry.py

"""Python-owned catalog of built-in runtime tools."""

from typing import Any

from pydantic_ai import RunContext

from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolPolicy,
)


async def get_runtime_context(ctx: RunContext[RuntimeDeps]) -> dict[str, str | None]:
    """Return the current Praxis runtime context for this turn."""
    deps = ctx.deps
    return {
        "workspace_id": str(deps.run.workspace_id),
        "conversation_id": str(deps.conversation.id),
        "agent_id": str(deps.agent.id),
        "run_id": str(deps.run.id),
        "agent_name": deps.agent.name,
        "agent_slug": deps.agent.slug,
    }


def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


RUNTIME_TOOL_CATALOG: dict[str, RuntimeToolDefinition] = {
    "get_runtime_context": RuntimeToolDefinition(
        name="get_runtime_context",
        function=get_runtime_context,
        description="Read the current Praxis workspace, conversation, agent, and run identifiers.",
        takes_ctx=True,
        timeout=5,
    ),
    "add_numbers": RuntimeToolDefinition(
        name="add_numbers",
        function=add_numbers,
        description="Add two integers.",
        timeout=5,
        max_retries=1,
    ),
}


def build_runtime_tools(agent: Agent):
    """Resolve an agent row's configured tools into Pydantic AI tools."""
    tool_names = _normalize_tool_names(agent.tool_names or [])
    policies = _normalize_tool_policies(agent.tool_policies or {})
    tools = []

    for name in tool_names:
        definition = RUNTIME_TOOL_CATALOG.get(name)
        if definition is None:
            raise ModelConfigurationError(
                "Unknown runtime tool configured on agent",
                details={
                    "agent_id": str(agent.id),
                    "tool_name": name,
                    "available_tools": sorted(RUNTIME_TOOL_CATALOG),
                },
            )
        tools.append(
            definition.to_pydantic_tool(
                policy=policies.get(name, definition.default_policy),
            )
        )

    return tools


def _normalize_tool_names(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ModelConfigurationError(
            "Agent tool_names must be a list",
            details={"tool_names_type": type(raw).__name__},
        )
    normalized = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise ModelConfigurationError(
                "Agent tool_names contains an invalid tool name",
                details={"tool_name": value},
            )
        normalized.append(value.strip())
    return normalized


def _normalize_tool_policies(raw: Any) -> dict[str, ToolPolicy]:
    if not isinstance(raw, dict):
        raise ModelConfigurationError(
            "Agent tool_policies must be an object",
            details={"tool_policies_type": type(raw).__name__},
        )

    policies: dict[str, ToolPolicy] = {}
    for name, policy in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ModelConfigurationError(
                "Agent tool_policies contains an invalid tool name",
                details={"tool_name": name},
            )
        if policy not in {TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL}:
            raise ModelConfigurationError(
                "Agent tool_policies contains an invalid policy",
                details={
                    "tool_name": name,
                    "tool_policy": policy,
                    "valid_tool_policies": [TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL],
                },
            )
        policies[name.strip()] = policy
    return policies
