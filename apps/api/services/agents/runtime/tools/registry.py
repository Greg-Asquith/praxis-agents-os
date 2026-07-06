# apps/api/services/agents/runtime/tools/registry.py
# ruff: noqa: E402

"""Python-owned catalog of built-in runtime tools."""

import logging
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel

from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError, ResolvedModel
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_KIND_CAPABILITY,
    TOOL_KIND_FUNCTION,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolEffect,
    ToolKind,
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
    kind: ToolKind = TOOL_KIND_FUNCTION,
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
    capability_factory: Callable[[], Any] | None = None,
    supported_model_providers: Iterable[str] | None = None,
    configurable: bool = True,
    auto_mount: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a Python function as a runtime tool."""

    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        normalized_supported_providers = (
            frozenset(supported_model_providers) if supported_model_providers is not None else None
        )
        definition = RuntimeToolDefinition(
            name=name,
            function=function if kind == TOOL_KIND_FUNCTION else None,
            description=description,
            provider=provider,
            label=label or _derive_label(name),
            kind=kind,
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
            capability_factory=capability_factory,
            supported_model_providers=normalized_supported_providers,
            configurable=configurable,
            auto_mount=auto_mount,
        )
        validate_definition(definition)
        if definition.name in RUNTIME_TOOL_CATALOG:
            raise RuntimeError(f"Duplicate runtime tool name: {definition.name}")
        RUNTIME_TOOL_CATALOG[definition.name] = definition
        return function

    return decorator


def build_runtime_tools(agent: Agent, *, include_delegation: bool = False):
    """Resolve an agent row's configured tools into Pydantic AI tools."""
    tool_names = [
        *(
            definition.name
            for definition in sorted(
                RUNTIME_TOOL_CATALOG.values(),
                key=lambda tool_definition: tool_definition.name,
            )
            if definition.auto_mount and definition.kind == TOOL_KIND_FUNCTION
        ),
        *_normalize_tool_names(agent.tool_names or []),
    ]
    policies = _normalize_tool_policies(agent.tool_policies or {})
    tools = []
    mounted_tool_names: set[str] = set()

    for name in tool_names:
        if name in mounted_tool_names:
            continue
        mounted_tool_names.add(name)
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
        if definition.kind == TOOL_KIND_CAPABILITY:
            continue
        if not permissions.is_tool_allowed(definition, workspace=None, agent=agent):
            logger.info(
                "Skipping disallowed runtime tool %s for agent %s",
                definition.name,
                agent.id,
            )
            continue
        tools.append(
            definition.to_pydantic_tool(
                policy=TOOL_POLICY_AUTO
                if definition.auto_mount
                else policies.get(name, definition.default_policy),
            )
        )

    if include_delegation:
        from services.agents.runtime.delegation import build_delegation_tools

        tools.extend(build_delegation_tools())

    return tools


def build_runtime_native_capabilities(
    agent: Agent,
    resolved_model: ResolvedModel,
) -> list[Any]:
    """Resolve an agent row's configured capability-backed runtime entries."""
    tool_names = _normalize_tool_names(agent.tool_names or [])
    capabilities = []

    for name in tool_names:
        definition = RUNTIME_TOOL_CATALOG.get(name)
        if definition is None or definition.kind != TOOL_KIND_CAPABILITY:
            continue
        if not permissions.is_tool_allowed(definition, workspace=None, agent=agent):
            logger.info(
                "Skipping disallowed native capability %s for agent %s",
                definition.name,
                agent.id,
            )
            continue
        if (
            definition.supported_model_providers is not None
            and resolved_model.provider not in definition.supported_model_providers
        ):
            logger.info(
                "Skipping native capability %s for provider %s",
                definition.name,
                resolved_model.provider,
            )
            continue
        if definition.capability_factory is None:
            raise ModelConfigurationError(
                "Runtime capability entry is missing a factory",
                details={"tool_name": definition.name},
            )
        capabilities.append(definition.capability_factory())

    return capabilities


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
            if definition.configurable
            and permissions.is_tool_allowed(definition, workspace=workspace, agent=agent)
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
from services.agents.runtime.tools import (
    files as _files,  # noqa: F401
    native as _native,  # noqa: F401
    planning as _planning,  # noqa: F401
)
