# apps/api/services/agents/runtime/tools/contract.py

"""Runtime tool catalog value types."""

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field
from typing import Annotated, Any, Literal, get_args, get_origin, get_type_hints

from pydantic import BaseModel
from pydantic_ai import Tool

from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.context import RuntimeDeps

ToolPolicy = Literal["auto", "approval"]
ToolEffect = Literal["read", "write"]
ToolEffectScope = Literal["internal", "external"]
ToolEgress = Literal["none", "provider_query", "arbitrary_url", "external_write"]
ToolFieldFormat = Literal[
    "text",
    "multiline",
    "markdown",
    "html",
    "bytes",
    "datetime",
    "boolean",
    "url",
    "list",
    "number",
    "keyvalue",
    "records",
    "entity",
    "entity_list",
]

TOOL_POLICY_AUTO: ToolPolicy = "auto"
TOOL_POLICY_APPROVAL: ToolPolicy = "approval"
VALID_TOOL_POLICIES = frozenset({TOOL_POLICY_AUTO, TOOL_POLICY_APPROVAL})
TOOL_EFFECT_READ: ToolEffect = "read"
TOOL_EFFECT_WRITE: ToolEffect = "write"
VALID_TOOL_EFFECTS = frozenset({TOOL_EFFECT_READ, TOOL_EFFECT_WRITE})
TOOL_EFFECT_SCOPE_INTERNAL: ToolEffectScope = "internal"
TOOL_EFFECT_SCOPE_EXTERNAL: ToolEffectScope = "external"
VALID_TOOL_EFFECT_SCOPES = frozenset({TOOL_EFFECT_SCOPE_INTERNAL, TOOL_EFFECT_SCOPE_EXTERNAL})
TOOL_EGRESS_NONE: ToolEgress = "none"
TOOL_EGRESS_PROVIDER_QUERY: ToolEgress = "provider_query"
TOOL_EGRESS_ARBITRARY_URL: ToolEgress = "arbitrary_url"
TOOL_EGRESS_EXTERNAL_WRITE: ToolEgress = "external_write"
VALID_TOOL_EGRESS = frozenset(
    {
        TOOL_EGRESS_NONE,
        TOOL_EGRESS_PROVIDER_QUERY,
        TOOL_EGRESS_ARBITRARY_URL,
        TOOL_EGRESS_EXTERNAL_WRITE,
    }
)
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_TOOL_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_CODE_MODE_MACHINERY_TOOL_NAMES = frozenset(
    {
        "delegate_to_agent",
        "list_delegate_agents",
        "load_capability",
        "report_completion",
        "run_code",
        "run_script",
        "run_workflow",
    }
)
_INTEGRATION_PARAMETER_DENYLIST = frozenset(
    {
        "account_id",
        "base_id",
        "connection_id",
        "connection_label",
        "customer_id",
        "integration_resource_id",
        "mailbox",
        "principal",
        "resource_id",
    }
)
VALID_TOOL_FIELD_FORMATS = frozenset(
    {
        "text",
        "multiline",
        "markdown",
        "html",
        "bytes",
        "datetime",
        "boolean",
        "url",
        "list",
        "number",
        "keyvalue",
        "records",
        "entity",
        "entity_list",
    }
)
EDITABLE_TOOL_FIELD_FORMATS = frozenset(
    {
        "text",
        "multiline",
        "markdown",
        "html",
        "number",
        "list",
        "keyvalue",
        "records",
        "entity",
        "entity_list",
    }
)
STRING_TOOL_FIELD_FORMATS = frozenset({"text", "multiline", "markdown"})
RECORDS_FIELD_MAX_ROWS = 500
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
        "mail",
        "gmail",
        "google_ads",
        "airtable",
        "bigquery",
        "chart",
        "workflow",
    }
)


@dataclass(frozen=True)
class ToolFieldColumn:
    """One declared scalar column in a records argument field."""

    key: str
    label: str
    options: tuple[str, ...] = ()
    placeholder: str = ""
    required: bool = False


@dataclass(frozen=True)
class ToolFieldPresentation:
    """One argument or result key rendered as a labelled field in the web client."""

    key: str
    label: str
    format: ToolFieldFormat = "text"
    editable: bool = False
    placeholder: str = ""
    options: tuple[str, ...] = ()
    secondary: bool = False
    entity_kind: str | None = None
    depends_on: tuple[str, ...] = ()
    columns: tuple[ToolFieldColumn, ...] = ()
    min_rows: int = 0


@dataclass(frozen=True)
class ToolPresentation:
    """Declarative display config for one tool; `{key}` templates resolve client-side."""

    icon: str = "tool"
    running_label: str = ""
    completed_label: str = ""
    failed_label: str = ""
    approval_title: str = ""
    approval_prompt: str = ""
    approve_label: str = ""
    arg_fields: tuple[ToolFieldPresentation, ...] = ()
    result_fields: tuple[ToolFieldPresentation, ...] = ()


@dataclass(frozen=True)
class IntegrationToolBinding:
    """Provider/resource compatibility declared by one integration tool."""

    provider_keys: frozenset[str]
    resource_types: frozenset[str]
    requires_write: bool = False


@dataclass(frozen=True)
class RuntimeToolDefinition:
    """One Python-owned runtime tool entry."""

    name: str
    function: Callable[..., Any]
    description: str
    version: int = 1
    provider: str = "core"
    label: str = ""
    effect: ToolEffect = TOOL_EFFECT_READ
    effect_scope: ToolEffectScope = TOOL_EFFECT_SCOPE_INTERNAL
    egress: ToolEgress = TOOL_EGRESS_NONE
    code_eligible: bool = False
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
    max_result_chars: int | None = None
    """Optional free-text result bound overriding the runtime default."""
    max_public_result_chars: int | None = None
    """Maximum serialized characters allowed in explicit transcript-only output."""
    configurable: bool = True
    auto_mount: bool = False
    always_allowed_when_mounted: bool = False
    integration_binding: IntegrationToolBinding | None = None
    availability_check: Callable[[], bool] | None = None
    presentation: ToolPresentation = ToolPresentation()
    _serialized_input_schema: dict[str, Any] | None = dataclass_field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _input_schema_cached: bool = dataclass_field(
        default=False,
        init=False,
        repr=False,
        compare=False,
    )

    def allowed_policies(self) -> frozenset[ToolPolicy]:
        """Return the policies this tool can run under."""
        allowed: set[ToolPolicy] = set()
        if self.supports_auto:
            allowed.add(TOOL_POLICY_AUTO)
        if self.supports_approval:
            allowed.add(TOOL_POLICY_APPROVAL)
        return frozenset(allowed)

    def serialized_input_schema(self) -> dict[str, Any] | None:
        """Return the registration-cached JSON schema for function arguments."""
        if not self._input_schema_cached:
            schema = self.to_pydantic_tool().tool_def.parameters_json_schema
            object.__setattr__(self, "_serialized_input_schema", schema)
            object.__setattr__(self, "_input_schema_cached", True)
        return self._serialized_input_schema

    def to_pydantic_tool(self, *, policy: ToolPolicy | None = None) -> Tool[RuntimeDeps]:
        """Build the Pydantic AI tool instance for one turn."""
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
    if definition.version < 1:
        raise RuntimeError("Runtime tool version must be greater than or equal to one")
    if definition.effect not in VALID_TOOL_EFFECTS:
        raise RuntimeError("Runtime tool effect must be read or write")
    if definition.effect_scope not in VALID_TOOL_EFFECT_SCOPES:
        raise RuntimeError("Runtime tool effect scope must be internal or external")
    if definition.egress not in VALID_TOOL_EGRESS:
        raise RuntimeError("Runtime tool egress must be a known classification")
    if definition.code_eligible and (
        definition.name in _CODE_MODE_MACHINERY_TOOL_NAMES
        or definition.always_allowed_when_mounted
        or definition.defer_loading
    ):
        raise RuntimeError("Runtime machinery and deferred tools cannot be code eligible")
    if definition.max_result_chars is not None and definition.max_result_chars < 1:
        raise RuntimeError("Runtime tool max_result_chars must be greater than zero")
    if definition.max_public_result_chars is not None and definition.max_public_result_chars < 1:
        raise RuntimeError("Runtime tool max_public_result_chars must be greater than zero")
    if (
        definition.effect == TOOL_EFFECT_READ
        and definition.effect_scope != TOOL_EFFECT_SCOPE_INTERNAL
    ):
        raise RuntimeError("Read runtime tools must use internal effect scope")
    if definition.effect == TOOL_EFFECT_READ and definition.effect_scope_resolver is not None:
        raise RuntimeError("Read runtime tools cannot provide an effect scope resolver")
    is_external_write = definition.effect == TOOL_EFFECT_WRITE and (
        definition.effect_scope == TOOL_EFFECT_SCOPE_EXTERNAL
        or definition.effect_scope_resolver is not None
    )
    if (definition.egress == TOOL_EGRESS_EXTERNAL_WRITE) != is_external_write:
        raise RuntimeError(
            "External-effect write runtime tools must use external_write egress, and only those tools may use it"
        )
    if (
        definition.effect == TOOL_EFFECT_WRITE
        and not is_external_write
        and definition.egress != TOOL_EGRESS_NONE
    ):
        raise RuntimeError("Internal-only write runtime tools must use none egress")
    _validate_integration_binding(definition)
    _validate_presentation(definition)

    allowed_policies = definition.allowed_policies()
    if not allowed_policies:
        raise RuntimeError("Runtime tool must support at least one policy")
    if definition.default_policy not in allowed_policies:
        raise RuntimeError("Runtime tool default policy must be supported by the tool")
    if definition.auto_mount and definition.configurable:
        raise RuntimeError("Auto-mounted runtime tools cannot be configurable")
    if definition.always_allowed_when_mounted and (
        definition.configurable
        or definition.effect_scope != TOOL_EFFECT_SCOPE_INTERNAL
        or definition.default_policy != TOOL_POLICY_AUTO
        or not definition.supports_auto
        or definition.supports_approval
    ):
        raise RuntimeError(
            "Always-allowed runtime tools must be non-configurable, internal, and auto-only"
        )
    if (
        definition.effect == TOOL_EFFECT_WRITE
        and not definition.supports_approval
        and not definition.auto_mount
        and not definition.always_allowed_when_mounted
    ):
        raise RuntimeError("Write runtime tools must support approval policy")


def _validate_integration_binding(definition: RuntimeToolDefinition) -> None:
    binding = definition.integration_binding
    if binding is None:
        return
    if not binding.provider_keys or not binding.resource_types:
        raise RuntimeError("Integration bindings require provider keys and resource types")

    from services.integrations.manifest import PROVIDER_KEY_PATTERN, PROVIDER_MANIFESTS

    if any(not PROVIDER_KEY_PATTERN.fullmatch(key) for key in binding.provider_keys):
        raise RuntimeError("Integration binding provider keys must be lowercase snake_case")
    if any(not _TOOL_PROVIDER_PATTERN.fullmatch(kind) for kind in binding.resource_types):
        raise RuntimeError("Integration binding resource types must be lowercase tokens")
    unknown_providers = binding.provider_keys.difference(PROVIDER_MANIFESTS)
    if unknown_providers:
        raise RuntimeError(
            f"Integration binding has unknown provider keys: {', '.join(sorted(unknown_providers))}"
        )
    declared_resource_types = {
        resource_type
        for provider_key in binding.provider_keys
        for resource_type in PROVIDER_MANIFESTS[provider_key].resource_types
    }
    unknown_resource_types = binding.resource_types.difference(declared_resource_types)
    if unknown_resource_types:
        raise RuntimeError(
            "Integration binding has undeclared resource types: "
            f"{', '.join(sorted(unknown_resource_types))}"
        )
    if binding.requires_write and definition.effect != TOOL_EFFECT_WRITE:
        raise RuntimeError("Write-required integration bindings require a write tool")
    if definition.egress == TOOL_EGRESS_EXTERNAL_WRITE and not binding.requires_write:
        raise RuntimeError("External-write integration tools require a write-required binding")
    parameter_names = set(inspect.signature(definition.function).parameters)
    if parameter_names.intersection(_INTEGRATION_PARAMETER_DENYLIST):
        raise RuntimeError(
            "Integration tools must not take connection/account parameters; context is server-resolved"
        )
    type_hints = get_type_hints(definition.function, include_extras=True)
    for parameter in inspect.signature(definition.function).parameters.values():
        _validate_nested_integration_parameter(type_hints.get(parameter.name, parameter.annotation))


def _validate_nested_integration_parameter(
    annotation: Any,
    seen_models: set[type[BaseModel]] | None = None,
) -> None:
    """Permit scope keys only inside the registered scoped-reference base type."""
    from services.agents.runtime.entity_references.domain import ScopedEntityReference

    if seen_models is None:
        seen_models = set()
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            _validate_nested_integration_parameter(args[0], seen_models)
        return
    if origin is not None:
        for argument in get_args(annotation):
            _validate_nested_integration_parameter(argument, seen_models)
        return
    if not inspect.isclass(annotation) or not issubclass(annotation, BaseModel):
        return
    if annotation in seen_models:
        return
    seen_models.add(annotation)
    nested_names = set(annotation.model_fields)
    forbidden = nested_names.intersection(_INTEGRATION_PARAMETER_DENYLIST)
    if forbidden and not issubclass(annotation, ScopedEntityReference):
        raise RuntimeError(
            "Integration scope fields are allowed only inside registered scoped references"
        )
    for field in annotation.model_fields.values():
        _validate_nested_integration_parameter(field.annotation, seen_models)


def _validate_presentation(definition: RuntimeToolDefinition) -> None:
    presentation = definition.presentation
    if presentation.icon not in VALID_TOOL_ICONS:
        raise RuntimeError(
            f"Runtime tool presentation icon must be one of the known tokens, got {presentation.icon!r}"
        )
    if presentation.approve_label and not presentation.approve_label.strip():
        raise RuntimeError("Runtime tool presentation approve label must not be blank")
    for field in (*presentation.arg_fields, *presentation.result_fields):
        if not field.key.strip():
            raise RuntimeError("Runtime tool presentation field keys must not be blank")
        if not field.label.strip():
            raise RuntimeError("Runtime tool presentation field labels must not be blank")
        if field.format not in VALID_TOOL_FIELD_FORMATS:
            raise RuntimeError(
                f"Runtime tool presentation field format must be one of the known formats, got {field.format!r}"
            )
        if field.editable and field.format not in EDITABLE_TOOL_FIELD_FORMATS:
            raise RuntimeError(
                "Editable runtime tool presentation fields must use an editable format"
            )
        if (field.options or field.placeholder) and not field.editable:
            raise RuntimeError(
                "Runtime tool presentation field options and placeholders require editable fields"
            )
        if field.options and field.format not in STRING_TOOL_FIELD_FORMATS:
            raise RuntimeError(
                "Runtime tool presentation field options require a string-shaped format"
            )
        normalized_options = [option.strip() for option in field.options]
        if any(not option for option in normalized_options):
            raise RuntimeError("Runtime tool presentation field options must not be blank")
        if len(normalized_options) != len(set(normalized_options)):
            raise RuntimeError("Runtime tool presentation field options must be unique")
        if field.columns and field.format != "records":
            raise RuntimeError("Runtime tool presentation field columns require the records format")
        if field.format == "records" and not field.columns:
            raise RuntimeError("Records runtime tool presentation fields require columns")
        if type(field.min_rows) is not int or field.min_rows < 0:
            raise RuntimeError(
                "Runtime tool presentation field min_rows must be a non-negative integer"
            )
        if field.format != "records" and field.min_rows != 0:
            raise RuntimeError(
                "Runtime tool presentation field min_rows requires the records format"
            )
        if field.min_rows > RECORDS_FIELD_MAX_ROWS:
            raise RuntimeError(
                f"Runtime tool presentation field min_rows cannot exceed {RECORDS_FIELD_MAX_ROWS}"
            )
        column_keys = [column.key for column in field.columns]
        if len(column_keys) != len(set(column_keys)):
            raise RuntimeError("Runtime tool presentation record column keys must be unique")
        for column in field.columns:
            if type(column.required) is not bool:
                raise RuntimeError(
                    "Runtime tool presentation record column required must be a boolean"
                )
            if not _TOOL_NAME_PATTERN.fullmatch(column.key):
                raise RuntimeError(
                    "Runtime tool presentation record column keys must be lowercase snake_case"
                )
            if not column.label.strip():
                raise RuntimeError(
                    "Runtime tool presentation record column labels must not be blank"
                )
            normalized_column_options = [option.strip() for option in column.options]
            if any(not option for option in normalized_column_options):
                raise RuntimeError(
                    "Runtime tool presentation record column options must not be blank"
                )
            if len(normalized_column_options) != len(set(normalized_column_options)):
                raise RuntimeError("Runtime tool presentation record column options must be unique")
        is_entity = field.format in {"entity", "entity_list"}
        if is_entity and field.entity_kind is None:
            raise RuntimeError("Entity runtime tool presentation fields require an entity kind")
        if not is_entity and field.entity_kind is not None:
            raise RuntimeError("Non-entity runtime tool presentation fields cannot set entity kind")
        if field.entity_kind is not None and not _TOOL_NAME_PATTERN.fullmatch(field.entity_kind):
            raise RuntimeError("Runtime tool presentation entity kind must be lowercase snake_case")
        if field.depends_on and not is_entity:
            raise RuntimeError(
                "Only entity runtime tool presentation fields can declare dependencies"
            )
        if len(field.depends_on) != len(set(field.depends_on)):
            raise RuntimeError("Runtime tool presentation field dependencies must be unique")
        if field.key in field.depends_on:
            raise RuntimeError("Runtime tool presentation fields cannot depend on themselves")
    for field in presentation.result_fields:
        if field.editable:
            raise RuntimeError("Runtime tool result presentation fields cannot be editable")
        if field.secondary:
            raise RuntimeError("Runtime tool result presentation fields cannot be secondary")
    schema = definition.serialized_input_schema()
    properties = set(schema.get("properties", {})) if isinstance(schema, dict) else set()
    for field in presentation.arg_fields:
        unknown_dependencies = set(field.depends_on).difference(properties)
        if unknown_dependencies:
            raise RuntimeError(
                "Runtime tool presentation field dependencies must name input arguments: "
                f"{', '.join(sorted(unknown_dependencies))}"
            )
