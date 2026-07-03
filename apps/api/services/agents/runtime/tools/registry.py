# apps/api/services/agents/runtime/tools/registry.py

"""Python-owned catalog of built-in runtime tools."""

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolEffect,
    ToolPolicy,
    validate_definition,
)

logger = logging.getLogger(__name__)

RUNTIME_TOOL_CATALOG: dict[str, RuntimeToolDefinition] = {}


def runtime_tool(
    *,
    name: str,
    description: str,
    provider: str = "core",
    label: str | None = None,
    effect: ToolEffect = TOOL_EFFECT_READ,
    default_policy: ToolPolicy = TOOL_POLICY_AUTO,
    supports_auto: bool = True,
    supports_approval: bool = True,
    takes_ctx: bool = False,
    timeout: float | None = None,
    max_retries: int | None = None,
    args_validator: Callable[..., Any] | None = None,
    defer_loading: bool = False,
    output_model: type[BaseModel] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a Python function as a runtime tool."""

    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        definition = RuntimeToolDefinition(
            name=name,
            function=function,
            description=description,
            provider=provider,
            label=label or _derive_label(name),
            effect=effect,
            takes_ctx=takes_ctx,
            default_policy=default_policy,
            supports_auto=supports_auto,
            supports_approval=supports_approval,
            timeout=timeout,
            max_retries=max_retries,
            args_validator=args_validator,
            defer_loading=defer_loading,
            output_model=output_model,
        )
        validate_definition(definition)
        if definition.name in RUNTIME_TOOL_CATALOG:
            raise RuntimeError(f"Duplicate runtime tool name: {definition.name}")
        RUNTIME_TOOL_CATALOG[definition.name] = definition
        return function

    return decorator


def build_runtime_tools(agent: Agent, *, include_delegation: bool = False):
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
        if not permissions.is_tool_allowed(definition, workspace=None, agent=agent):
            logger.info(
                "Skipping disallowed runtime tool %s for agent %s",
                definition.name,
                agent.id,
            )
            continue
        tools.append(
            definition.to_pydantic_tool(
                policy=policies.get(name, definition.default_policy),
            )
        )

    if include_delegation:
        from services.agents.runtime.delegation import build_delegation_tools

        tools.extend(build_delegation_tools())

    return tools


def list_allowed_tool_definitions(
    *,
    workspace: object | None,
    agent: Agent | None = None,
) -> list[RuntimeToolDefinition]:
    """Return registry entries visible in the supplied workspace context."""
    return sorted(
        (
            definition
            for definition in RUNTIME_TOOL_CATALOG.values()
            if permissions.is_tool_allowed(definition, workspace=workspace, agent=agent)
        ),
        key=lambda definition: (definition.provider, definition.name),
    )


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


def _derive_label(name: str) -> str:
    return name.replace("_", " ").capitalize()


# Import provider modules for registration side effects.
from services.agents.runtime.tools import core as _core  # noqa: E402, F401
