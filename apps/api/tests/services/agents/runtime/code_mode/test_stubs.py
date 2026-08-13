"""Contract tests for code-mode catalog and schema-to-stub rendering."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel

from integrations.airtable.tools import TOOL_DEFINITIONS as AIRTABLE_TOOL_DEFINITIONS
from integrations.bigquery.tools import TOOL_DEFINITIONS as BIGQUERY_TOOL_DEFINITIONS
from integrations.gmail.tools import TOOL_DEFINITIONS as GMAIL_TOOL_DEFINITIONS
from integrations.google_ads.tools import TOOL_DEFINITIONS as GOOGLE_ADS_TOOL_DEFINITIONS
from services.agents.runtime.code_mode.stubs import (
    CodeModeCatalog,
    UnsupportedCodeModeSchemaError,
    render_stub_catalog,
    render_tool_stub,
)
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG


class _NestedFilter(BaseModel):
    enabled: bool = True
    labels: list[str] | None = None


class _EntityReference(BaseModel):
    entity_kind: Literal["example"] = "example"
    label: str
    entity_id: str


def _schema_matrix_tool(
    query: str,
    entity: _EntityReference,
    filters: _NestedFilter | None = None,
    values: list[int | str] | None = None,
) -> dict[str, object]:
    return {"query": query, "entity": entity, "filters": filters, "values": values}


SCHEMA_MATRIX_DEFINITION = RuntimeToolDefinition(
    name="schema_matrix",
    function=_schema_matrix_tool,
    description="Exercise the complete supported schema matrix.",
    code_eligible=True,
)


def test_stub_catalog_renders_keyword_only_signatures_and_named_shapes() -> None:
    rendered = render_tool_stub(SCHEMA_MATRIX_DEFINITION)

    assert "class _EntityReference(TypedDict):" in rendered
    assert "entity_kind: NotRequired[Literal['example']]" in rendered
    assert "class _NestedFilter(TypedDict):" in rendered
    assert "labels: NotRequired[list[str] | None]" in rendered
    assert (
        "async def schema_matrix(*, query: str, entity: _EntityReference, "
        "filters: _NestedFilter | None = None, values: list[int | str] | None = None) -> Any"
        in rendered
    )


def test_catalog_description_uses_probe_pinned_workflow_guidance() -> None:
    catalog = CodeModeCatalog.build(((SCHEMA_MATRIX_DEFINITION, "auto"),))

    assert catalog.tool_names == ("schema_matrix",)
    assert "Run one short tool workflow" in catalog.tool_description
    assert "classes, decorators, async code, and type-checked signatures" in (
        catalog.tool_description
    )
    assert "asyncio, collections, dataclasses" in catalog.tool_description
    assert "Environment,\nwall-clock, and filesystem access are unavailable" in (
        catalog.tool_description
    )
    assert "one\nworkflow per task" in catalog.tool_description


def test_every_first_party_eligible_schema_renders() -> None:
    definitions = {
        definition.name: definition
        for definition in (
            *RUNTIME_TOOL_CATALOG.values(),
            *AIRTABLE_TOOL_DEFINITIONS,
            *BIGQUERY_TOOL_DEFINITIONS,
            *GMAIL_TOOL_DEFINITIONS,
            *GOOGLE_ADS_TOOL_DEFINITIONS,
        )
        if definition.code_eligible
    }

    rendered = render_stub_catalog(tuple(definitions.values()))

    assert definitions
    for name in definitions:
        assert f"async def {name}(" in rendered


def test_unsupported_schema_keyword_fails_closed() -> None:
    definition = RuntimeToolDefinition(
        name="unsupported_schema",
        function=lambda value: value,
        description="Unsupported on purpose.",
        code_eligible=True,
    )
    object.__setattr__(
        definition,
        "_serialized_input_schema",
        {
            "type": "object",
            "properties": {"value": {"type": "string", "not": {"const": "blocked"}}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    object.__setattr__(definition, "_input_schema_cached", True)

    with pytest.raises(UnsupportedCodeModeSchemaError, match="unsupported schema keywords: not"):
        render_tool_stub(definition)
