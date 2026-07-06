# apps/api/services/agents/runtime/tools/contract.py

"""Runtime tool catalog value types."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Tool

from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.context import RuntimeDeps

ToolPolicy = Literal["auto", "approval"]
ToolEffect = Literal["read", "write"]
ToolKind = Literal["function", "capability"]

TOOL_POLICY_AUTO: ToolPolicy = "auto"
TOOL_POLICY_APPROVAL: ToolPolicy = "approval"
VALID_TOOL_POLICIES = frozenset({TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL})
TOOL_EFFECT_READ: ToolEffect = "read"
TOOL_EFFECT_WRITE: ToolEffect = "write"
VALID_TOOL_EFFECTS = frozenset({TOOL_EFFECT_READ, TOOL_EFFECT_WRITE})
TOOL_KIND_FUNCTION: ToolKind = "function"
TOOL_KIND_CAPABILITY: ToolKind = "capability"
VALID_TOOL_KINDS = frozenset({TOOL_KIND_FUNCTION, TOOL_KIND_CAPABILITY})
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_TOOL_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class RuntimeToolDefinition:
    """One Python-owned runtime tool entry."""

    name: str
    function: Callable[..., Any] | None
    description: str
    provider: str = "core"
    label: str = ""
    kind: ToolKind = TOOL_KIND_FUNCTION
    effect: ToolEffect = TOOL_EFFECT_READ
    takes_ctx: bool = False
    default_policy: ToolPolicy = TOOL_POLICY_AUTO
    supports_auto: bool = True
    supports_approval: bool = True
    timeout: float | None = None
    max_retries: int | None = None
    args_validator: Callable[..., Any] | None = None
    defer_loading: bool = False
    output_model: type[BaseModel] | None = None
    """Declared output contract, enforced by the tool dispatch layer."""
    capability_factory: Callable[[], Any] | None = None
    supported_model_providers: frozenset[str] | None = None
    configurable: bool = True
    auto_mount: bool = False

    def allowed_policies(self) -> frozenset[ToolPolicy]:
        """Return the policies this tool can run under."""
        allowed: set[ToolPolicy] = set()
        if self.supports_auto:
            allowed.add(TOOL_POLICY_AUTO)
        if self.supports_approval:
            allowed.add(TOOL_POLICY_APPROVAL)
        return frozenset(allowed)

    def to_pydantic_tool(self, *, policy: ToolPolicy | None = None) -> Tool[RuntimeDeps]:
        """Build the Pydantic AI tool instance for one turn."""
        if self.kind != TOOL_KIND_FUNCTION or self.function is None:
            raise ModelConfigurationError(
                "Runtime capability entries cannot be mounted as function tools",
                details={"tool_name": self.name, "tool_kind": self.kind},
            )
        resolved_policy = policy or self.default_policy
        if resolved_policy not in VALID_TOOL_POLICIES:
            raise ModelConfigurationError(
                "Unknown runtime tool policy",
                details={
                    "tool_name": self.name,
                    "tool_policy": resolved_policy,
                    "valid_tool_policies": sorted(VALID_TOOL_POLICIES),
                },
            )
        allowed_policies = self.allowed_policies()
        if resolved_policy not in allowed_policies:
            raise ModelConfigurationError(
                "Runtime tool policy is not supported by this tool",
                details={
                    "tool_name": self.name,
                    "tool_policy": resolved_policy,
                    "allowed_tool_policies": sorted(allowed_policies),
                },
            )

        return Tool(
            self.function,
            takes_ctx=self.takes_ctx,
            name=self.name,
            description=self.description,
            max_retries=self.max_retries,
            requires_approval=resolved_policy == TOOL_POLICY_APPROVAL,
            args_validator=self.args_validator,
            timeout=self.timeout,
            defer_loading=self.defer_loading,
        )


def validate_definition(definition: RuntimeToolDefinition) -> None:
    """Validate import-time invariants for one runtime tool definition."""
    if not _TOOL_NAME_PATTERN.fullmatch(definition.name):
        raise RuntimeError("Runtime tool name must be non-blank snake_case starting with a letter")
    if not _TOOL_PROVIDER_PATTERN.fullmatch(definition.provider):
        raise RuntimeError("Runtime tool provider must be a lowercase token starting with a letter")
    if not definition.description.strip():
        raise RuntimeError("Runtime tool description must not be blank")
    if definition.kind not in VALID_TOOL_KINDS:
        raise RuntimeError("Runtime tool kind must be function or capability")
    if definition.effect not in VALID_TOOL_EFFECTS:
        raise RuntimeError("Runtime tool effect must be read or write")
    if definition.supported_model_providers is not None:
        for provider in definition.supported_model_providers:
            if not _TOOL_PROVIDER_PATTERN.fullmatch(provider):
                raise RuntimeError(
                    "Runtime tool supported model providers must be lowercase tokens"
                )

    if definition.kind == TOOL_KIND_FUNCTION:
        if definition.function is None:
            raise RuntimeError("Function runtime tools must provide a function")
        if definition.capability_factory is not None:
            raise RuntimeError("Function runtime tools cannot provide a capability factory")
    else:
        if definition.function is not None:
            raise RuntimeError("Capability runtime tools cannot provide a function")
        if definition.capability_factory is None:
            raise RuntimeError("Capability runtime tools must provide a capability factory")
        if definition.effect != TOOL_EFFECT_READ:
            raise RuntimeError("Capability runtime tools must be read-only")
        if definition.takes_ctx:
            raise RuntimeError("Capability runtime tools cannot take RunContext")
        if definition.timeout is not None:
            raise RuntimeError("Capability runtime tools cannot set a function timeout")
        if definition.max_retries is not None:
            raise RuntimeError("Capability runtime tools cannot set function retries")
        if definition.args_validator is not None:
            raise RuntimeError("Capability runtime tools cannot set an args validator")
        if definition.output_model is not None:
            raise RuntimeError("Capability runtime tools cannot set an output model")
        if definition.supports_approval:
            raise RuntimeError("Capability runtime tools cannot support approval policy")
        if definition.auto_mount:
            raise RuntimeError("Capability runtime tools cannot be auto-mounted")

    allowed_policies = definition.allowed_policies()
    if not allowed_policies:
        raise RuntimeError("Runtime tool must support at least one policy")
    if definition.default_policy not in allowed_policies:
        raise RuntimeError("Runtime tool default policy must be supported by the tool")
    if definition.auto_mount and definition.configurable:
        raise RuntimeError("Auto-mounted runtime tools cannot be configurable")
    if (
        definition.effect == TOOL_EFFECT_WRITE
        and not definition.supports_approval
        and not definition.auto_mount
    ):
        raise RuntimeError("Write runtime tools must support approval policy")
