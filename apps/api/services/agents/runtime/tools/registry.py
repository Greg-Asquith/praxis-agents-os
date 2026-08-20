# apps/api/services/agents/runtime/tools/registry.py
"""Python-owned catalog of built-in runtime tools."""

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from models.agent import Agent
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.delegation.build_delegation_tools import (
    DELEGATION_TOOL_DEFINITIONS,
    build_delegation_tools,
)
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
from services.agents.runtime.tools.workspace_tools import RESERVED_WORKSPACE_TOOL_PREFIXES

if TYPE_CHECKING:
    from services.integrations.context.domain import ResolvedActiveContext

logger = logging.getLogger(__name__)

RUNTIME_TOOL_CATALOG: dict[str, RuntimeToolDefinition] = {}


def register_tool_definition(definition: RuntimeToolDefinition) -> None:
    """Register a provider-contributed definition in the singular catalog."""
    if definition.name.startswith(RESERVED_WORKSPACE_TOOL_PREFIXES):
        raise RuntimeError(
            f"Runtime tool name uses a reserved workspace-defined prefix: {definition.name}"
        )
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

    return next(
        (definition for definition in DELEGATION_TOOL_DEFINITIONS if definition.name == name),
        None,
    )


def resolve_runtime_tool_definition(
    name: str,
    workspace_definitions: Sequence[RuntimeToolDefinition] = (),
) -> RuntimeToolDefinition | None:
    """Resolve a per-run workspace definition before the immutable static catalog."""
    workspace_definition = next(
        (definition for definition in workspace_definitions if definition.name == name),
        None,
    )
    return workspace_definition or get_runtime_tool_definition(name)


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
    code_eligible: bool = False,
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
    max_public_result_chars: int | None = None,
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
            code_eligible=code_eligible,
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
            max_public_result_chars=max_public_result_chars,
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
    wrapped_tool_names: list[str] | None = None,
    workspace: object | None = None,
    disabled_tool_names: frozenset[str] = frozenset(),
    additional_tool_names: Sequence[str] = (),
    workspace_definitions: Sequence[RuntimeToolDefinition] = (),
):
    """Resolve an agent row's configured tools into Pydantic AI tools."""
    # Importing the Code Mode package while this registry initializes reaches dispatch.
    from services.agents.runtime.code_mode.stubs import (
        CodeModeCatalog,
        UnsupportedCodeModeSchemaError,
        render_tool_stub,
    )
    from services.agents.runtime.tools.code_mode import (
        RUN_WORKFLOW_TOOL_NAME,
        build_run_workflow_tool,
    )

    code_mode_enabled = bool(agent.code_mode_enabled)
    definition_lookup = {
        **RUNTIME_TOOL_CATALOG,
        **{definition.name: definition for definition in workspace_definitions},
    }
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
        *(
            name
            for name in _normalize_tool_names(agent.tool_names or [])
            if name != RUN_WORKFLOW_TOOL_NAME
        ),
    ]
    if code_mode_enabled:
        tool_names.append(RUN_WORKFLOW_TOOL_NAME)
    policies = _normalize_tool_policies(agent.tool_policies or {})
    tools = []
    wrapped_entries: list[tuple[RuntimeToolDefinition, ToolPolicy]] = []
    mounted_tool_names: set[str] = set()
    mount_run_workflow = False

    for name in tool_names:
        if name in mounted_tool_names:
            continue
        mounted_tool_names.add(name)
        definition = definition_lookup.get(name)
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
        if name == RUN_WORKFLOW_TOOL_NAME:
            mount_run_workflow = code_mode_enabled
            continue
        effective_policy = (
            definition.default_policy
            if definition.auto_mount
            else policies.get(name, definition.default_policy)
        )
        if code_mode_enabled and definition.code_eligible and not definition.defer_loading:
            try:
                render_tool_stub(definition)
            except UnsupportedCodeModeSchemaError as exc:
                logger.warning(
                    "Keeping code-eligible runtime tool %s directly mounted because its schema "
                    "cannot be rendered: %s",
                    definition.name,
                    exc,
                    extra={
                        "agent_id": str(agent.id),
                        "tool_name": definition.name,
                    },
                )
            else:
                wrapped_entries.append((definition, effective_policy))
                if wrapped_tool_names is not None:
                    wrapped_tool_names.append(definition.name)
                continue
        tools.append(definition.to_pydantic_tool(policy=effective_policy))

    if mount_run_workflow:
        tools.append(build_run_workflow_tool(CodeModeCatalog.build(wrapped_entries)))

    if include_delegation:
        tools.extend(build_delegation_tools())

    return tools


def list_allowed_tool_definitions(
    *,
    workspace: object | None,
    agent: Agent | None = None,
    disabled_tool_names: frozenset[str] = frozenset(),
    workspace_definitions: Sequence[RuntimeToolDefinition] = (),
) -> list[RuntimeToolDefinition]:
    """Return registry entries visible in the supplied workspace context."""
    return sorted(
        (
            definition
            for definition in (*RUNTIME_TOOL_CATALOG.values(), *workspace_definitions)
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


def list_tool_presentations(
    workspace_definitions: Sequence[RuntimeToolDefinition] = (),
) -> list[RuntimeToolDefinition]:
    """Return every first-party runtime entry's display metadata."""
    return sorted(
        (
            *RUNTIME_TOOL_CATALOG.values(),
            *DELEGATION_TOOL_DEFINITIONS,
            *workspace_definitions,
        ),
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
