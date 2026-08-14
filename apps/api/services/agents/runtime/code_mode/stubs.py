# apps/api/services/agents/runtime/code_mode/stubs.py

"""Per-run code-mode catalogs and model-facing Python stub rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai.toolsets import FunctionToolset

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import RuntimeToolDefinition, ToolPolicy

_SANDBOX_GUIDANCE = """Run one short tool workflow in the restricted Python sandbox.
Use wrapped functions for data work and direct tools for conversation-shaped actions. Prefer one
workflow per task. Call every wrapped function with `await` and keyword arguments, and leave the
workflow's answer as the last expression. The signatures below are reference documentation; do
not redefine them.

Treat wrapped-tool results as intermediate variables, not as the workflow answer. Use Python to
filter, join, aggregate, rank, branch, or derive identifiers and arguments for later calls. Return
only compact, decision-ready data with relevant counts and caveats. Do not merely collect
independent tool responses or return whole raw payloads unless the user explicitly requests raw
data and the payload is already small. For fan-out results, inspect each result entry's `data`;
the outer `results` length is the number of resources queried, not the number of provider rows.
Do not return samples that still contain a whole fan-out entry. Governed nested calls execute
serially; `asyncio.gather` does not make them parallel.

The pinned sandbox supports classes, decorators, async code, and type-checked signatures. Allowed
imports are asyncio, collections, dataclasses, datetime, itertools, json, math, os, pathlib, re,
sys, typing, and unicodedata. It has no network modules or third-party imports. Environment,
wall-clock, and filesystem access are unavailable because no OS handler or mount is provided."""

_SCHEMA_METADATA_KEYS = frozenset(
    {
        "default",
        "description",
        "examples",
        "format",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "title",
    }
)
_IDENTIFIER_PARTS = re.compile(r"[^0-9A-Za-z]+")


class UnsupportedCodeModeSchemaError(ValueError):
    """A tool schema cannot be represented faithfully in the v1 stub subset."""


@dataclass(frozen=True)
class CodeModeCatalog:
    """The singular wrapped-tool catalog closed over by one `run_workflow` tool."""

    definitions: tuple[RuntimeToolDefinition, ...]
    effective_policies: tuple[tuple[str, ToolPolicy], ...]
    stub_text: str
    tool_description: str
    wrapped_toolset: FunctionToolset[RuntimeDeps]

    @classmethod
    def build(
        cls,
        entries: Sequence[tuple[RuntimeToolDefinition, ToolPolicy]],
    ) -> CodeModeCatalog:
        """Build one deterministic catalog from already-authorized per-run entries."""
        ordered = tuple(sorted(entries, key=lambda entry: entry[0].name))
        stub_text = render_stub_catalog(tuple(definition for definition, _policy in ordered))
        tool_description = render_run_workflow_description(stub_text)
        return cls(
            definitions=tuple(definition for definition, _policy in ordered),
            effective_policies=tuple((definition.name, policy) for definition, policy in ordered),
            stub_text=stub_text,
            tool_description=tool_description,
            wrapped_toolset=FunctionToolset(
                tools=[
                    definition.to_pydantic_tool(policy=policy) for definition, policy in ordered
                ],
                sequential=True,
            ),
        )

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Return the wrapped function names in stable catalog order."""
        return tuple(definition.name for definition in self.definitions)


def render_run_workflow_description(stub_text: str) -> str:
    """Render the tool description and sandbox truth from the same catalog source."""
    catalog = stub_text or "# No wrapped functions are available for this run."
    return f"{_SANDBOX_GUIDANCE}\n\nAvailable wrapped functions:\n```python\n{catalog}\n```"


def render_tool_stub(definition: RuntimeToolDefinition) -> str:
    """Render one definition or raise when its schema is outside the supported subset."""
    return render_stub_catalog((definition,))


def render_stub_catalog(definitions: Sequence[RuntimeToolDefinition]) -> str:
    """Render deterministic input/output shapes and async function signatures."""
    inputs: list[tuple[RuntimeToolDefinition, Mapping[str, Any]]] = []
    merged_defs: dict[str, Any] = {}
    output_schemas: dict[type[Any], Mapping[str, Any]] = {}
    for definition in definitions:
        raw_input_schema = definition.serialized_input_schema()
        if not isinstance(raw_input_schema, Mapping):
            raise UnsupportedCodeModeSchemaError(f"{definition.name} has no object input schema")
        input_schema = _strip_schema_titles(raw_input_schema)
        _validate_root_schema(definition.name, input_schema)
        _merge_definitions(merged_defs, input_schema, owner=definition.name)
        inputs.append((definition, input_schema))

    schemas: list[tuple[RuntimeToolDefinition, Mapping[str, Any], Mapping[str, Any] | None]] = []
    for definition, input_schema in inputs:
        output_schema: Mapping[str, Any] | None = None
        if definition.output_model is not None:
            output_schema = output_schemas.get(definition.output_model)
            if output_schema is None:
                output_model_name = _python_identifier(definition.output_model.__name__)
                root_schema = _merge_output_definitions(
                    merged_defs,
                    _strip_schema_titles(
                        definition.output_model.model_json_schema(mode="serialization")
                    ),
                    prefix=output_model_name,
                    owner=f"{definition.name} output",
                )
                existing = merged_defs.get(output_model_name)
                if existing is not None and existing != root_schema:
                    raise UnsupportedCodeModeSchemaError(
                        f"{definition.name} output conflicts with schema {output_model_name}"
                    )
                merged_defs[output_model_name] = root_schema
                output_schema = {"$ref": f"#/$defs/{output_model_name}"}
                output_schemas[definition.output_model] = output_schema
        schemas.append((definition, input_schema, output_schema))

    renderer = _SchemaRenderer(merged_defs)
    functions: list[str] = []
    for definition, input_schema, output_schema in schemas:
        properties = _mapping(input_schema.get("properties", {}), key="properties")
        required = _required_keys(input_schema, properties)
        parameters: list[str] = []
        for name, property_schema in properties.items():
            if not isinstance(name, str) or not name.isidentifier():
                raise UnsupportedCodeModeSchemaError(
                    f"{definition.name} has a non-Python parameter name: {name!r}"
                )
            type_expr = renderer.type_expr(
                property_schema,
                hint=f"{_pascal(definition.name)}{_pascal(name)}",
            )
            if name in required:
                parameters.append(f"{name}: {type_expr}")
            else:
                default = property_schema.get("default", None)
                parameters.append(f"{name}: {type_expr} = {default!r}")
        signature = ", ".join(("*", *parameters)) if parameters else ""
        return_type = (
            renderer.type_expr(
                output_schema,
                hint=f"{_pascal(definition.name)}Result",
            )
            if output_schema is not None
            else "Any"
        )
        description = " ".join(definition.description.split())
        functions.append(
            f"async def {definition.name}({signature}) -> {return_type}: ...  # {description}"
        )

    blocks: list[str] = []
    if renderer.aliases:
        blocks.append("from typing import Any, Literal, NotRequired, TypedDict")
        blocks.extend(renderer.aliases)
    elif functions:
        blocks.append("from typing import Any, Literal")
    blocks.extend(functions)
    return "\n\n".join(blocks)


def _merge_definitions(
    merged: dict[str, Any],
    schema: Mapping[str, Any],
    *,
    owner: str,
) -> None:
    for name, value in _mapping(schema.get("$defs", {}), key=f"{owner}.$defs").items():
        existing = merged.get(name)
        if existing is not None and existing != value:
            raise UnsupportedCodeModeSchemaError(f"{owner} has a conflicting $defs entry: {name}")
        merged[name] = value


def _schema_without_definitions(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    return {key: value for key, value in schema.items() if key != "$defs"}


def _merge_output_definitions(
    merged: dict[str, Any],
    schema: Mapping[str, Any],
    *,
    prefix: str,
    owner: str,
) -> Mapping[str, Any]:
    """Merge output $defs under their own names, prefixing only genuine conflicts.

    Shared entity types (e.g. provider references) keep one catalog-wide name so a
    tool result visibly returns the same type another tool accepts. A definition is
    prefixed with the output model's name only when a different schema already owns
    its name; renames cascade because they change referencing definitions too.
    """
    definitions = _mapping(schema.get("$defs", {}), key=f"{owner}.$defs")
    conflicted: set[str] = set()
    while True:
        renamed = {
            name: f"{prefix}{_python_identifier(name)}"
            if name in conflicted
            else _python_identifier(name)
            for name in definitions
        }
        rewritten = {
            renamed[name]: _rewrite_references(value, renamed, owner=owner)
            for name, value in definitions.items()
        }
        newly_conflicted = {
            name
            for name in definitions
            if name not in conflicted
            and renamed[name] in merged
            and merged[renamed[name]] != rewritten[renamed[name]]
        }
        if not newly_conflicted:
            break
        conflicted |= newly_conflicted
    for name, value in rewritten.items():
        existing = merged.get(name)
        if existing is not None and existing != value:
            raise UnsupportedCodeModeSchemaError(f"{owner} has a conflicting $defs entry: {name}")
        merged[name] = value
    return _rewrite_references(_schema_without_definitions(schema), renamed, owner=owner)


def _strip_schema_titles(value: Any) -> Any:
    """Drop unused title metadata so structurally equal schemas merge under one name."""
    if isinstance(value, list):
        return [_strip_schema_titles(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    stripped: dict[str, Any] = {}
    for key, item in value.items():
        if key == "title":
            continue
        if key in {"properties", "$defs"} and isinstance(item, Mapping):
            # Keys here are property/definition names, not schema keywords.
            stripped[key] = {name: _strip_schema_titles(child) for name, child in item.items()}
            continue
        stripped[key] = _strip_schema_titles(item)
    return stripped


def _rewrite_references(value: Any, renamed: Mapping[str, str], *, owner: str) -> Any:
    if isinstance(value, list):
        return [_rewrite_references(item, renamed, owner=owner) for item in value]
    if not isinstance(value, Mapping):
        return value
    rewritten: dict[str, Any] = {}
    for key, item in value.items():
        if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/"):
            name = item.removeprefix("#/$defs/")
            replacement = renamed.get(name)
            if replacement is None:
                raise UnsupportedCodeModeSchemaError(
                    f"{owner} references missing $defs entry {name}"
                )
            rewritten[key] = f"#/$defs/{replacement}"
            continue
        rewritten[key] = _rewrite_references(item, renamed, owner=owner)
    return rewritten


class _SchemaRenderer:
    def __init__(self, definitions: Mapping[str, Any]) -> None:
        self._definitions = definitions
        self._rendered_aliases: dict[str, str] = {}
        self._visiting: set[str] = set()

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(self._rendered_aliases.values())

    def type_expr(self, raw_schema: Any, *, hint: str) -> str:
        schema = _mapping(raw_schema, key=hint)
        if "$ref" in schema:
            _reject_unknown_keys(schema, {"$ref"}, hint=hint)
            reference = schema["$ref"]
            prefix = "#/$defs/"
            if not isinstance(reference, str) or not reference.startswith(prefix):
                raise UnsupportedCodeModeSchemaError(f"{hint} has an unsupported reference")
            name = reference.removeprefix(prefix)
            target = self._definitions.get(name)
            if target is None:
                raise UnsupportedCodeModeSchemaError(
                    f"{hint} references missing $defs entry {name}"
                )
            identifier = _python_identifier(name)
            if identifier in self._visiting:
                return repr(identifier)
            self._ensure_alias(name, target)
            return identifier
        if "anyOf" in schema:
            _reject_unknown_keys(schema, {"anyOf"}, hint=hint)
            variants = schema["anyOf"]
            if not isinstance(variants, list) or not variants:
                raise UnsupportedCodeModeSchemaError(f"{hint} has an empty anyOf")
            rendered = [
                self.type_expr(variant, hint=f"{hint}Option{index + 1}")
                for index, variant in enumerate(variants)
            ]
            return " | ".join(dict.fromkeys(rendered))
        if "oneOf" in schema:
            _reject_unknown_keys(schema, {"oneOf"}, hint=hint)
            variants = schema["oneOf"]
            if not isinstance(variants, list) or not variants:
                raise UnsupportedCodeModeSchemaError(f"{hint} has an empty oneOf")
            rendered = [
                self.type_expr(variant, hint=f"{hint}Option{index + 1}")
                for index, variant in enumerate(variants)
            ]
            return " | ".join(dict.fromkeys(rendered))
        if "enum" in schema or "const" in schema:
            structural = {"enum"} if "enum" in schema else {"const"}
            structural.add("type")
            _reject_unknown_keys(schema, structural, hint=hint)
            values = schema.get("enum", [schema.get("const")])
            if not isinstance(values, list) or not values:
                raise UnsupportedCodeModeSchemaError(f"{hint} has an empty enum")
            return "Literal[" + ", ".join(repr(value) for value in values) + "]"

        schema_type = schema.get("type")
        if schema_type == "string":
            _reject_unknown_keys(schema, {"type"}, hint=hint)
            return "str"
        if schema_type == "integer":
            _reject_unknown_keys(schema, {"type"}, hint=hint)
            return "int"
        if schema_type == "number":
            _reject_unknown_keys(schema, {"type"}, hint=hint)
            return "float"
        if schema_type == "boolean":
            _reject_unknown_keys(schema, {"type"}, hint=hint)
            return "bool"
        if schema_type == "null":
            _reject_unknown_keys(schema, {"type"}, hint=hint)
            return "None"
        if schema_type == "array":
            _reject_unknown_keys(schema, {"type", "items"}, hint=hint)
            if "items" not in schema:
                raise UnsupportedCodeModeSchemaError(f"{hint} array has no item schema")
            return f"list[{self.type_expr(schema['items'], hint=f'{hint}Item')}]"
        if schema_type == "object":
            _reject_unknown_keys(
                schema,
                {"type", "properties", "required", "additionalProperties"},
                hint=hint,
            )
            properties = _mapping(schema.get("properties", {}), key=f"{hint}.properties")
            if properties:
                alias = _python_identifier(hint)
                self._ensure_alias(alias, schema)
                return alias
            additional = schema.get("additionalProperties", False)
            if additional is True:
                return "dict[str, Any]"
            if isinstance(additional, Mapping):
                return f"dict[str, {self.type_expr(additional, hint=f'{hint}Value')}]"
            if additional is False:
                return "dict[str, Any]"
        raise UnsupportedCodeModeSchemaError(f"{hint} uses an unsupported schema shape")

    def _ensure_alias(self, raw_name: str, raw_schema: Any) -> None:
        name = _python_identifier(raw_name)
        schema = _mapping(raw_schema, key=name)
        if name in self._rendered_aliases:
            return
        if name in self._visiting:
            return
        if schema.get("type") != "object" or not schema.get("properties"):
            self._visiting.add(name)
            try:
                expression = self.type_expr(schema, hint=name)
            finally:
                self._visiting.remove(name)
            self._rendered_aliases[name] = f"{name} = {expression}"
            return
        _reject_unknown_keys(
            schema,
            {"type", "properties", "required", "additionalProperties"},
            hint=name,
        )
        properties = _mapping(schema.get("properties", {}), key=f"{name}.properties")
        required = _required_keys(schema, properties)
        self._visiting.add(name)
        try:
            fields: list[str] = []
            for field_name, field_schema in properties.items():
                if not isinstance(field_name, str) or not field_name.isidentifier():
                    raise UnsupportedCodeModeSchemaError(
                        f"{name} has a non-Python field name: {field_name!r}"
                    )
                field_type = self.type_expr(
                    field_schema,
                    hint=f"{name}{_pascal(field_name)}",
                )
                if field_name not in required:
                    field_type = f"NotRequired[{field_type}]"
                fields.append(f"    {field_name}: {field_type}")
        finally:
            self._visiting.remove(name)
        body = "\n".join(fields) if fields else "    pass"
        self._rendered_aliases[name] = f"class {name}(TypedDict):\n{body}"


def _validate_root_schema(name: str, schema: Mapping[str, Any]) -> None:
    _reject_unknown_keys(
        schema,
        {"type", "properties", "required", "additionalProperties", "$defs"},
        hint=name,
    )
    if schema.get("type") != "object":
        raise UnsupportedCodeModeSchemaError(f"{name} input schema is not an object")
    if schema.get("additionalProperties", False) is not False:
        raise UnsupportedCodeModeSchemaError(
            f"{name} input schema allows undeclared keyword arguments"
        )
    _mapping(schema.get("properties", {}), key=f"{name}.properties")
    _required_keys(schema, _mapping(schema.get("properties", {}), key="properties"))


def _required_keys(schema: Mapping[str, Any], properties: Mapping[str, Any]) -> frozenset[str]:
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise UnsupportedCodeModeSchemaError("required must be a list of field names")
    if not set(required).issubset(properties):
        raise UnsupportedCodeModeSchemaError("required names a missing property")
    return frozenset(required)


def _reject_unknown_keys(
    schema: Mapping[str, Any],
    structural_keys: set[str],
    *,
    hint: str,
) -> None:
    unknown = set(schema) - structural_keys - _SCHEMA_METADATA_KEYS
    if unknown:
        raise UnsupportedCodeModeSchemaError(
            f"{hint} uses unsupported schema keywords: {', '.join(sorted(unknown))}"
        )


def _mapping(value: Any, *, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UnsupportedCodeModeSchemaError(f"{key} must be an object")
    return value


def _pascal(value: str) -> str:
    return "".join(part.capitalize() for part in _IDENTIFIER_PARTS.split(value) if part)


def _python_identifier(value: str) -> str:
    if value.isidentifier() and not value[0].isdigit():
        return value
    candidate = _pascal(value)
    if not candidate or candidate[0].isdigit():
        raise UnsupportedCodeModeSchemaError(f"schema name is not a Python identifier: {value!r}")
    return candidate
