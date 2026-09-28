# apps/api/tests/services/agents/runtime/code_mode/test_stubs.py

"""Contract tests for code-mode catalog and schema-to-stub rendering."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, create_model
from pydantic_monty import AsyncMonty, MontyTypingError

from integrations.airtable.tools import TOOL_DEFINITIONS as AIRTABLE_TOOL_DEFINITIONS
from integrations.bigquery.tools import TOOL_DEFINITIONS as BIGQUERY_TOOL_DEFINITIONS
from integrations.gmail.tools import TOOL_DEFINITIONS as GMAIL_TOOL_DEFINITIONS
from integrations.google_ads.tools import TOOL_DEFINITIONS as GOOGLE_ADS_TOOL_DEFINITIONS
from integrations.google_analytics.tools import (
    TOOL_DEFINITIONS as GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
)
from integrations.google_search_console.tools import (
    TOOL_DEFINITIONS as GOOGLE_SEARCH_CONSOLE_TOOL_DEFINITIONS,
)
from integrations.meta_ads.tools import TOOL_DEFINITIONS as META_ADS_TOOL_DEFINITIONS
from integrations.sharepoint.tools import TOOL_DEFINITIONS as SHAREPOINT_TOOL_DEFINITIONS
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
    description = " ".join(catalog.tool_description.split())

    assert catalog.tool_names == ("schema_matrix",)
    assert "Run one short Python workflow" in description
    assert "feeding identifiers from one result into later calls" in description
    assert "Call a tool directly when one call answers the question" in description
    assert "cannot read or create files; use `run_code`" in description
    assert "Prefer one workflow per task" in description
    assert "results as intermediate variables" in description
    assert "filter, join, aggregate, rank, branch" in description
    assert "Do not merely collect independent tool responses" in description
    assert "outer `results` length is the number of resources queried" in description
    assert "Do not return samples that still contain a whole fan-out entry" in description
    assert "`asyncio.gather` does not make them parallel" in description
    assert "A failed nested call raises `RuntimeError`" in description
    assert "a denied call raises `PermissionError`" in description
    assert "classes, dataclasses, decorators, async code, f-strings, `str.format`" in description
    assert "asyncio, base64, binascii, collections, copy, dataclasses, datetime" in description
    assert "environment and filesystem access are unavailable" in description
    assert "`datetime.now()` reads the current UTC time" in description
    assert "Sleeps return immediately" in description


async def test_every_first_party_eligible_schema_renders() -> None:
    definitions = {
        definition.name: definition
        for definition in (
            *RUNTIME_TOOL_CATALOG.values(),
            *AIRTABLE_TOOL_DEFINITIONS,
            *BIGQUERY_TOOL_DEFINITIONS,
            *GMAIL_TOOL_DEFINITIONS,
            *GOOGLE_ADS_TOOL_DEFINITIONS,
            *GOOGLE_ANALYTICS_TOOL_DEFINITIONS,
            *GOOGLE_SEARCH_CONSOLE_TOOL_DEFINITIONS,
            *SHAREPOINT_TOOL_DEFINITIONS,
            *META_ADS_TOOL_DEFINITIONS,
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
    entries = tuple((definition, definition.default_policy) for definition in definitions.values())
    assert (
        CodeModeCatalog.build(entries).stub_text == CodeModeCatalog.build(entries[::-1]).stub_text
    )
    compile(rendered, "catalogue.pyi", "exec")
    async with (
        AsyncMonty() as pool,
        pool.checkout(type_check=True, type_check_stubs=rendered) as session,
    ):
        assert await session.feed_run("1") == 1


async def test_keyword_output_fields_compile_and_are_consumable_in_monty() -> None:
    output = create_model("MessageOutput", **{"from": (str, ...)})

    async def read_message() -> dict[str, str]:
        return {"from": "sender@example.com"}

    definition = RuntimeToolDefinition(
        name="read_message",
        function=read_message,
        description="Reads a message sender.",
        code_eligible=True,
        output_model=output,
    )
    rendered = render_tool_stub(definition)
    compile(rendered, "message.pyi", "exec")
    async with (
        AsyncMonty() as pool,
        pool.checkout(type_check=True, type_check_stubs=rendered) as session,
    ):
        assert (
            await session.feed_run(
                'message = await read_message()\nmessage["from"].upper()',
                external_lookup={"read_message": read_message},
            )
            == "SENDER@EXAMPLE.COM"
        )
    async with (
        AsyncMonty() as pool,
        pool.checkout(type_check=True, type_check_stubs=rendered) as session,
    ):
        with pytest.raises(MontyTypingError):
            await session.feed_run('message = await read_message()\nmessage["from"] + 1')


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


@pytest.mark.parametrize(
    "name,output,fields",
    [
        (
            "meta_ads_get_accounts",
            "MetaAdsAccountsOutput",
            ["spend_cap_remaining: MetaAdsMoney | None", "timezone_name: MetaAdsText | None"],
        ),
        (
            "meta_ads_list_objects",
            "MetaAdsObjectsOutput",
            ["object_count: int", "currency: str", "objects: list["],
        ),
        (
            "meta_ads_list_custom_conversions",
            "MetaAdsCustomConversionsOutput",
            [
                "conversion_count: int",
                "conversions: list[",
                "is_archived: NotRequired[bool | None]",
            ],
        ),
        (
            "meta_ads_list_activities",
            "MetaAdsActivitiesOutput",
            [
                "event_count: int",
                "events: list[",
                "old_value: MetaAdsChangeValue | None",
                "timezone_name: MetaAdsText",
            ],
        ),
    ],
)
def test_meta_ads_discovery_stubs_have_typed_account_data(name, output, fields) -> None:
    definition = next(item for item in META_ADS_TOOL_DEFINITIONS if item.name == name)
    rendered = render_tool_stub(definition)
    assert f"async def {name}(" in rendered
    assert f"-> {output}" in rendered
    for field in fields:
        assert field in rendered
    assert "integration_resource_id" not in rendered
    assert "connection_id" not in rendered
    assert definition.code_eligible
