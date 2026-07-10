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
ToolEffectScope = Literal["internal", "external"]
ToolKind = Literal["function", "capability"]
ToolFieldFormat = Literal["text", "multiline", "markdown", "bytes", "datetime", "boolean"]

TOOL_POLICY_AUTO: ToolPolicy = "auto"
TOOL_POLICY_APPROVAL: ToolPolicy = "approval"
VALID_TOOL_POLICIES = frozenset({TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL})
TOOL_EFFECT_READ: ToolEffect = "read"
TOOL_EFFECT_WRITE: ToolEffect = "write"
VALID_TOOL_EFFECTS = frozenset({TOOL_EFFECT_READ, TOOL_EFFECT_WRITE})
TOOL_EFFECT_SCOPE_INTERNAL: ToolEffectScope = "internal"
TOOL_EFFECT_SCOPE_EXTERNAL: ToolEffectScope = "external"
VALID_TOOL_EFFECT_SCOPES = frozenset({TOOL_EFFECT_SCOPE_INTERNAL, TOOL_EFFECT_SCOPE_EXTERNAL})
TOOL_KIND_FUNCTION: ToolKind = "function"
TOOL_KIND_CAPABILITY: ToolKind = "capability"
VALID_TOOL_KINDS = frozenset({TOOL_KIND_FUNCTION, TOOL_KIND_CAPABILITY})
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_TOOL_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
VALID_TOOL_FIELD_FORMATS = frozenset(
    {"text", "multiline", "markdown", "bytes", "datetime", "boolean"}
)
# Semantic icon tokens the web client maps to concrete icons.
VALID_TOOL_ICONS = frozenset(
    {
        "tool",
        "file",
        "file-plus",
        "files",
        "search",
        "globe",
        "list-todo",
        "sparkles",
        "bot",
        "image",
        "book",
        "link",
    }
)


@dataclass(frozen=True)
class ToolFieldPresentation:
    """One argument or result key rendered as a labelled field in the web client."""

    key: str
    label: str
    format: ToolFieldFormat = "text"


@dataclass(frozen=True)
class ToolPresentation:
    """Declarative display config for one tool; `{key}` templates resolve client-side."""

    icon: str = "tool"
    running_label: str = ""
    completed_label: str = ""
    failed_label: str = ""
    approval_title: str = ""
    approval_prompt: str = ""
    arg_fields: tuple[ToolFieldPresentation, ...] = ()
    result_fields: tuple[ToolFieldPresentation, ...] = ()


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
    effect_scope: ToolEffectScope = TOOL_EFFECT_SCOPE_INTERNAL
    takes_ctx: bool = False
    default_policy: ToolPolicy = TOOL_POLICY_AUTO
    supports_auto: bool = True
    supports_approval: bool = True
    timeout: float | None = None
    max_retries: int | None = None
    args_validator: Callable[..., Any] | None = None
    defer_loading: bool = False
    effect_scope_resolver: Callable[[dict[str, Any]], ToolEffectScope] | None = None
    output_model: type[BaseModel] | None = None
    """Declared output contract, enforced by the tool dispatch layer."""
    capability_factory: Callable[[], Any] | None = None
    supported_model_providers: frozenset[str] | None = None
    configurable: bool = True
    auto_mount: bool = False
    presentation: ToolPresentation = ToolPresentation()

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
    if definition.effect_scope not in VALID_TOOL_EFFECT_SCOPES:
        raise RuntimeError("Runtime tool effect scope must be internal or external")
    if (
        definition.effect == TOOL_EFFECT_READ
        and definition.effect_scope != TOOL_EFFECT_SCOPE_INTERNAL
    ):
        raise RuntimeError("Read runtime tools must use internal effect scope")
    if definition.effect == TOOL_EFFECT_READ and definition.effect_scope_resolver is not None:
        raise RuntimeError("Read runtime tools cannot provide an effect scope resolver")
    if definition.supported_model_providers is not None:
        for provider in definition.supported_model_providers:
            if not _TOOL_PROVIDER_PATTERN.fullmatch(provider):
                raise RuntimeError(
                    "Runtime tool supported model providers must be lowercase tokens"
                )
    _validate_presentation(definition.presentation)

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
        if definition.effect_scope_resolver is not None:
            raise RuntimeError("Capability runtime tools cannot set an effect scope resolver")
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


def _validate_presentation(presentation: ToolPresentation) -> None:
    if presentation.icon not in VALID_TOOL_ICONS:
        raise RuntimeError(
            f"Runtime tool presentation icon must be one of the known tokens, got {presentation.icon!r}"
        )
    for field in (*presentation.arg_fields, *presentation.result_fields):
        if not field.key.strip():
            raise RuntimeError("Runtime tool presentation field keys must not be blank")
        if not field.label.strip():
            raise RuntimeError("Runtime tool presentation field labels must not be blank")
        if field.format not in VALID_TOOL_FIELD_FORMATS:
            raise RuntimeError(
                f"Runtime tool presentation field format must be one of the known formats, got {field.format!r}"
            )
