# apps/api/services/agents/runtime/tools/registry.py
# ruff: noqa: E402

"""Python-owned catalog of built-in runtime tools."""

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.tools import permissions
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_POLICY_APPROVAL,
    TOOL_POLICY_AUTO,
    IntegrationToolBinding,
    RuntimeToolDefinition,
    ToolEffect,
    ToolEffectScope,
    ToolEgress,
    ToolPolicy,
    ToolPresentation,
    validate_definition,
)

if TYPE_CHECKING:
    from services.integrations.context.domain import ResolvedActiveContext

logger = logging.getLogger(__name__)

RUNTIME_TOOL_CATALOG: dict[str, RuntimeToolDefinition] = {}

from services.agents.runtime.entity_references.internal import register_internal_entity_resolvers

register_internal_entity_resolvers()


def register_tool_definition(definition: RuntimeToolDefinition) -> None:
    """Register a provider-contributed definition in the singular catalog."""
    validate_definition(definition)
    definition.serialized_input_schema()
    if definition.name in RUNTIME_TOOL_CATALOG:
        raise RuntimeError(f"Duplicate runtime tool name: {definition.name}")
    RUNTIME_TOOL_CATALOG[definition.name] = definition


def get_runtime_tool_definition(name: str) -> RuntimeToolDefinition | None:
    """Return a registered or runtime-owned tool definition."""
    definition = RUNTIME_TOOL_CATALOG.get(name)
    if definition is not None:
        return definition

    from services.agents.runtime.delegation.build_delegation_tools import (
        DELEGATION_TOOL_DEFINITIONS,
    )

    return next(
        (definition for definition in DELEGATION_TOOL_DEFINITIONS if definition.name == name),
        None,
    )


def runtime_tool(
    *,
    name: str,
    description: str,
    version: int = 1,
    provider: str = "core",
    label: str | None = None,
    effect: ToolEffect = TOOL_EFFECT_READ,
    effect_scope: ToolEffectScope = "internal",
    egress: ToolEgress = "none",
    default_policy: ToolPolicy = TOOL_POLICY_AUTO,
    supports_auto: bool = True,
    supports_approval: bool = True,
    takes_ctx: bool = False,
    timeout: float | None = None,
    max_retries: int | None = None,
    args_validator: Callable[..., Any] | None = None,
    defer_loading: bool = False,
    effect_scope_resolver: Callable[[dict[str, Any]], ToolEffectScope] | None = None,
    output_model: type[BaseModel] | None = None,
    max_result_chars: int | None = None,
    configurable: bool = True,
    auto_mount: bool = False,
    always_allowed_when_mounted: bool = False,
    integration_binding: IntegrationToolBinding | None = None,
    availability_check: Callable[[], bool] | None = None,
    presentation: ToolPresentation | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a Python function as a runtime tool."""

    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        definition = RuntimeToolDefinition(
            name=name,
            function=function,
            description=description,
            version=version,
            provider=provider,
            label=label or _derive_label(name),
            effect=effect,
            effect_scope=effect_scope,
            egress=egress,
            takes_ctx=takes_ctx,
            default_policy=default_policy,
            supports_auto=supports_auto,
            supports_approval=supports_approval,
            timeout=timeout,
            max_retries=max_retries,
            args_validator=args_validator,
            defer_loading=defer_loading,
            effect_scope_resolver=effect_scope_resolver,
            output_model=output_model,
            max_result_chars=max_result_chars,
            configurable=configurable,
            auto_mount=auto_mount,
            always_allowed_when_mounted=always_allowed_when_mounted,
            integration_binding=integration_binding,
            availability_check=availability_check,
            presentation=presentation or ToolPresentation(),
        )
        register_tool_definition(definition)
        return function

    return decorator


def build_runtime_tools(
    agent: Agent,
    *,
    include_delegation: bool = False,
    active_context: "ResolvedActiveContext | None" = None,
    skipped_tool_names: list[str] | None = None,
    workspace: object | None = None,
    disabled_tool_names: frozenset[str] = frozenset(),
    additional_tool_names: Sequence[str] = (),
):
    """Resolve an agent row's configured tools into Pydantic AI tools."""
    tool_names = [
        *(
            definition.name
            for definition in sorted(
                RUNTIME_TOOL_CATALOG.values(),
                key=lambda tool_definition: tool_definition.name,
            )
            if definition.auto_mount
        ),
        *additional_tool_names,
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
            if skipped_tool_names is not None:
                skipped_tool_names.append(name)
            logger.warning(
                "Skipping unavailable saved runtime tool %s for agent %s",
                name,
                agent.id,
                extra={"agent_id": str(agent.id), "skipped_tool_names": [name]},
            )
            continue
        if definition.integration_binding is not None and (
            active_context is None
            or not active_context.compatible_entries(definition.integration_binding)
        ):
            logger.info(
                "Skipping runtime tool %s without compatible active context",
                definition.name,
            )
            continue
        if not permissions.is_tool_allowed(
            definition,
            workspace=workspace,
            agent=agent,
            disabled_tool_names=disabled_tool_names,
        ):
            logger.info(
                "Skipping disallowed runtime tool %s for agent %s",
                definition.name,
                agent.id,
            )
            continue
        tools.append(
            definition.to_pydantic_tool(
                policy=definition.default_policy
                if definition.auto_mount
                else policies.get(name, definition.default_policy),
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
    disabled_tool_names: frozenset[str] = frozenset(),
) -> list[RuntimeToolDefinition]:
    """Return registry entries visible in the supplied workspace context."""
    return sorted(
        (
            definition
            for definition in RUNTIME_TOOL_CATALOG.values()
            if definition.configurable
            and permissions.is_tool_allowed(
                definition,
                workspace=workspace,
                agent=agent,
                disabled_tool_names=disabled_tool_names,
            )
        ),
        key=lambda definition: (definition.provider, definition.name),
    )


def list_tool_presentations() -> list[RuntimeToolDefinition]:
    """Return every first-party runtime entry's display metadata."""
    from services.agents.runtime.delegation.build_delegation_tools import (
        DELEGATION_TOOL_DEFINITIONS,
    )

    return sorted(
        (*RUNTIME_TOOL_CATALOG.values(), *DELEGATION_TOOL_DEFINITIONS),
        key=lambda definition: definition.name,
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
    artifacts as _artifacts,  # noqa: F401
    charting as _charting,  # noqa: F401
    completion as _completion,  # noqa: F401
    files as _files,  # noqa: F401
    kb as _kb,  # noqa: F401
    memory as _memory,  # noqa: F401
    native as _native,  # noqa: F401
    planning as _planning,  # noqa: F401
)
from services.integrations.loader import load_enabled_providers

load_enabled_providers()
