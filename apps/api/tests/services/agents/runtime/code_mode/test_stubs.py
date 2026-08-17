"""Contract tests for code-mode catalog and schema-to-stub rendering."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, create_model

from integrations.airtable.tools import TOOL_DEFINITIONS as AIRTABLE_TOOL_DEFINITIONS
from integrations.bigquery.tools import TOOL_DEFINITIONS as BIGQUERY_TOOL_DEFINITIONS
from integrations.gmail.tools import TOOL_DEFINITIONS as GMAIL_TOOL_DEFINITIONS
from integrations.google_ads.tools import TOOL_DEFINITIONS as GOOGLE_ADS_TOOL_DEFINITIONS
from integrations.google_analytics.tools import (
    TOOL_DEFINITIONS as GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
)
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


def test_output_definitions_unify_shared_types_and_prefix_only_conflicts() -> None:
    shape_a = create_model("SharedShape", value=(str, ...))
    shape_b = create_model("SharedShape", value=(int, ...))
    outputs = {
        "first_tool": create_model("FirstOutput", shape=(shape_a, ...)),
        "second_tool": create_model("SecondOutput", shape=(shape_b, ...)),
        "third_tool": create_model("ThirdOutput", shape=(shape_a, ...)),
    }

    def _noop() -> dict[str, object]:
        return {}

    rendered = render_stub_catalog(
        tuple(
            RuntimeToolDefinition(
                name=name,
                function=_noop,
                description="Conflict probe.",
                code_eligible=True,
                output_model=model,
            )
            for name, model in outputs.items()
        )
    )

    assert rendered.count("class SharedShape(TypedDict):") == 1
    assert "class SecondOutputSharedShape(TypedDict):" in rendered
    assert "ThirdOutputSharedShape" not in rendered
    assert "shape: SharedShape" in rendered
    assert "shape: SecondOutputSharedShape" in rendered


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
    assert "results as intermediate variables" in catalog.tool_description
    assert "filter, join, aggregate, rank, branch" in catalog.tool_description
    assert "Do not merely collect\nindependent tool responses" in catalog.tool_description
    assert "outer `results` length is the number of resources queried" in (catalog.tool_description)
    assert "Do not return samples that still contain a whole fan-out entry" in (
        catalog.tool_description
    )
    assert "`asyncio.gather` does not make them parallel" in catalog.tool_description


def test_google_ads_report_stub_declares_its_fan_out_and_row_envelope() -> None:
    definition = next(
        item for item in GOOGLE_ADS_TOOL_DEFINITIONS if item.name == "google_ads_run_report"
    )

    rendered = render_tool_stub(definition)

    assert "class GoogleAdsReportData(TypedDict):" in rendered
    assert "rows: list[dict[str, GoogleAdsJsonValue]]" in rendered
    assert "row_count: int" in rendered
    assert "class GoogleAdsRunReportOutput(TypedDict):" in rendered
    assert "async def google_ads_run_report(*, query: str) -> GoogleAdsRunReportOutput" in rendered
    assert "one fan-out entry per selected account" in rendered
    assert "`data.rows`" in rendered
    assert "mirrors the GAQL SELECT paths" in rendered


def test_every_first_party_eligible_schema_renders() -> None:
    definitions = {
        definition.name: definition
        for definition in (
            *RUNTIME_TOOL_CATALOG.values(),
            *AIRTABLE_TOOL_DEFINITIONS,
            *BIGQUERY_TOOL_DEFINITIONS,
            *GMAIL_TOOL_DEFINITIONS,
            *GOOGLE_ADS_TOOL_DEFINITIONS,
            *GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
        )
        if definition.code_eligible
    }

    rendered = render_stub_catalog(tuple(definitions.values()))

    assert definitions
    for name, definition in definitions.items():
        signature = next(
            line for line in rendered.splitlines() if line.startswith(f"async def {name}(")
        )
        if definition.output_model is not None:
            assert "-> Any" not in signature

    assert "class GoogleAdsCreateListOutcome(TypedDict):" in rendered
    # Created references render as the exact type the consumer tools accept.
    assert "reference: NotRequired[GoogleAdsSharedSetReference | None]" in rendered
    assert "negative_list: GoogleAdsSharedSetReference" in rendered
    assert "customer_id: str" in rendered
    assert "shared_set_id: str" in rendered
    assert "mailbox_id: str" in rendered
    assert "base_id: str" in rendered
    assert "integration_resource_id" not in rendered
    assert "connection_id" not in rendered


def test_classifier_is_rendered_in_the_code_mode_stub_catalog() -> None:
    definition = RUNTIME_TOOL_CATALOG["classify"]

    rendered = render_stub_catalog((definition,))

    assert "class ClassifiedItem(TypedDict):" in rendered
    assert "value: str" in rendered
    assert "class ClassifyOutput(TypedDict):" in rendered
    assert "results: list[ClassifiedItem]" in rendered
    assert (
        "async def classify(*, items: list[str], labels: list[str], instructions: str | None = None"
    ) in rendered
    assert "-> ClassifyOutput" in rendered


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
