"""Notion runtime-tool targeting, fan-out, audit, and output contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
)
from integrations.notion.references import (
    NotionDataSourceReference,
    NotionPageReference,
)
from integrations.notion.settings import notion_settings
from integrations.notion.tools import TOOL_DEFINITIONS, search_cursor
from integrations.notion.tools.query_data_source import notion_query_data_source
from integrations.notion.tools.read_page import notion_read_page
from integrations.notion.tools.schemas import (
    NotionDataSourceQueryData,
    NotionDataSourceQueryOutput,
    NotionPageOutput,
    NotionSearchData,
    NotionSearchOutput,
)
from integrations.notion.tools.search_cursor import decode_search_cursor, encode_search_cursor
from integrations.notion.tools.search_pages import COVERAGE_NOTE, notion_search_pages
from integrations.notion.tools.utils import bounded_notion_output
from services.agents.runtime.tools.permissions import is_tool_allowed
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.results import IntegrationContextResult


def entry(workspace_id: str) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="notion",
        resource_type="notion_workspace",
        external_id=workspace_id,
        display_name=f"Workspace {workspace_id}",
        connection_id=uuid4(),
        connection_label="Notion",
        connection_status="active",
        write_allowed=True,
    )


def context(*entries: ResolvedContextEntry, tool_name: str):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            db=object(),
            user=object(),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Notion Agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id=f"call-{tool_name}",
    )


def notion_text(content: str, source_ref: str, kind: str) -> UntrustedNode:
    return UntrustedNode(source_kind=kind, source_ref=source_ref, content=content)


def page_reference(workspace_id: str) -> NotionPageReference:
    return NotionPageReference(
        workspace_id=workspace_id,
        page_id="page-1",
        label="Launch plan",
        scope_label=f"Workspace {workspace_id}",
    )


def source_reference(workspace_id: str) -> NotionDataSourceReference:
    return NotionDataSourceReference(
        workspace_id=workspace_id,
        data_source_id="source-1",
        label="Projects",
        scope_label=f"Workspace {workspace_id}",
    )


async def async_value(value):
    return value


async def test_search_fans_out_with_safe_scope_attribution_and_partial_error(monkeypatch) -> None:
    first = entry("workspace-1")
    second = entry("workspace-2")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.notion.tools.search_pages.notion_client",
        lambda _ctx, selected: async_value(selected.external_id),
    )

    async def search(client, **_kwargs):
        if client == "workspace-2":
            raise IntegrationAuthError(
                "The Notion connection needs to be reconnected.",
                provider_key="notion",
                operation="search",
            )
        return {
            "items": [
                {
                    "kind": "page",
                    "id": "page-1",
                    "title": notion_text("Launch plan", "page-1", "notion_page"),
                    "url": "https://www.notion.so/page-1",
                    "last_edited_time": "2026-08-25T12:00:00Z",
                }
            ],
            "count": 1,
            "has_more": False,
            "next_cursor": None,
        }

    monkeypatch.setattr("integrations.notion.tools.search_pages.search", search)

    result = await notion_search_pages(
        context(first, second, tool_name="notion_search_pages"),
        query="launch",
    )

    assert [item["status"] for item in result["results"]] == ["success", "error"]
    success = result["results"][0]
    assert success["external_id"] == "workspace-1"
    assert success["data"]["coverage_note"] == COVERAGE_NOTE
    assert success["data"]["items"][0]["reference"].workspace_id == "workspace-1"
    assert result["results"][1]["error_code"] == "IntegrationAuthError"
    serialized = str(result)
    assert str(first.connection_id) not in serialized
    assert str(first.integration_resource_id) not in serialized
    assert audit.await_count == 2
    NotionSearchOutput.model_validate(result)


async def test_search_continuation_targets_only_the_workspace_that_issued_it(monkeypatch) -> None:
    first = entry("workspace-1")
    second = entry("workspace-2")
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "integrations.notion.tools.search_pages.notion_client",
        lambda _ctx, selected: async_value(selected.external_id),
    )

    async def search(client, **kwargs):
        calls.append((client, kwargs["start_cursor"]))
        return {
            "items": [],
            "count": 0,
            "has_more": True,
            "next_cursor": f"provider-{client}",
        }

    monkeypatch.setattr("integrations.notion.tools.search_pages.search", search)
    ctx = context(first, second, tool_name="notion_search_pages")

    initial = await notion_search_pages(ctx, query="launch")
    first_cursor = initial["results"][0]["data"]["next_cursor"]
    assert decode_search_cursor(first_cursor) == ("workspace-1", "provider-workspace-1")
    assert calls == [("workspace-1", None), ("workspace-2", None)]

    calls.clear()
    continued = await notion_search_pages(ctx, query="launch", start_cursor=first_cursor)

    assert calls == [("workspace-1", "provider-workspace-1")]
    assert [result["external_id"] for result in continued["results"]] == ["workspace-1"]
    NotionSearchOutput.model_validate(continued)


def test_search_cursor_round_trips_long_provider_value_verbatim() -> None:
    provider_cursor = ("opaque+/=_-" * 150) + "terminal"

    encoded = encode_search_cursor(
        workspace_id="workspace-1",
        provider_cursor=provider_cursor,
    )

    assert len(provider_cursor) > 1_000
    assert decode_search_cursor(encoded) == ("workspace-1", provider_cursor)


def test_search_cursor_rejects_oversized_encoded_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(search_cursor, "MAX_SCOPED_CURSOR_CHARS", 1)

    with pytest.raises(ModelRetry, match="continuation is invalid"):
        encode_search_cursor(
            workspace_id="workspace-1",
            provider_cursor="provider-cursor",
        )


async def test_search_rejects_invalid_or_inactive_continuations(monkeypatch) -> None:
    selected = entry("workspace-1")
    ctx = context(selected, tool_name="notion_search_pages")

    with pytest.raises(ModelRetry, match="continuation is invalid"):
        await notion_search_pages(ctx, start_cursor="not-a-scoped-cursor")

    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "integrations.notion.tools.search_pages.notion_client",
        lambda _ctx, chosen: async_value(chosen.external_id),
    )

    async def search(client, **_kwargs):
        return {
            "items": [],
            "count": 0,
            "has_more": True,
            "next_cursor": f"provider-{client}",
        }

    monkeypatch.setattr("integrations.notion.tools.search_pages.search", search)
    other_ctx = context(entry("workspace-2"), tool_name="notion_search_pages")
    initial = await notion_search_pages(other_ctx)
    inactive_cursor = initial["results"][0]["data"]["next_cursor"]

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await notion_search_pages(ctx, start_cursor=inactive_cursor)


@pytest.mark.parametrize(
    ("exception_type", "error_code"),
    [
        (IntegrationPermissionError, "IntegrationPermissionError"),
        (IntegrationNotFoundError, "IntegrationNotFoundError"),
    ],
)
async def test_page_provider_failure_is_an_audited_fan_out_error(
    monkeypatch, exception_type, error_code
) -> None:
    selected = entry("workspace-1")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.notion.tools.read_page.notion_client",
        lambda _ctx, _entry: async_value(object()),
    )

    async def get_page(_client, *, page_id):
        raise exception_type(
            "The selected Notion page could not be read.",
            provider_key="notion",
            operation="get_page",
        )

    monkeypatch.setattr("integrations.notion.tools.read_page.get_page", get_page)

    result = await notion_read_page(
        context(selected, tool_name="notion_read_page"),
        page_reference("workspace-1"),
    )

    assert result["results"][0]["status"] == "error"
    assert result["results"][0]["error_code"] == error_code
    assert audit.await_args.kwargs["error_code"] == error_code
    NotionPageOutput.model_validate(result)


async def test_read_page_returns_complete_truncation_evidence_and_external_ref(monkeypatch) -> None:
    selected = entry("workspace-1")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.notion.tools.read_page.notion_client",
        lambda _ctx, _entry: async_value(object()),
    )
    monkeypatch.setattr(
        "integrations.notion.tools.read_page.get_page",
        AsyncMock(
            return_value={
                "id": "page-1",
                "title": notion_text("Launch plan", "page-1", "notion_page"),
                "url": "https://www.notion.so/page-1",
                "last_edited_time": "2026-08-25T12:00:00Z",
            }
        ),
    )
    monkeypatch.setattr(
        "integrations.notion.tools.read_page.get_page_markdown",
        AsyncMock(
            return_value={
                "markdown": notion_text("# Launch plan", "page-1", "notion_page"),
                "bytes_returned": 13,
                "truncated": False,
                "provider_truncated": True,
                "unknown_block_count": 2,
            }
        ),
    )

    result = await notion_read_page(
        context(selected, tool_name="notion_read_page"),
        page_reference("workspace-1"),
    )

    data = result["results"][0]["data"]
    assert data["provider_truncated"] is True
    assert data["unknown_block_count"] == 2
    assert audit.await_args.kwargs["external_ref"] == "page-1"
    NotionPageOutput.model_validate(result)


async def test_query_returns_bounded_records_and_external_ref(monkeypatch) -> None:
    selected = entry("workspace-1")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )
    monkeypatch.setattr(
        "integrations.notion.tools.query_data_source.notion_client",
        lambda _ctx, _entry: async_value(object()),
    )
    monkeypatch.setattr(
        "integrations.notion.tools.query_data_source.query_data_source",
        AsyncMock(
            return_value={
                "records": [
                    {
                        "id": "record-1",
                        "kind": "page",
                        "title": notion_text("Alpha", "record-1", "notion_page"),
                        "url": "https://www.notion.so/record-1",
                        "last_edited_time": "2026-08-25T12:00:00Z",
                        "properties": {"Estimate": 8},
                        "properties_truncated": False,
                    }
                ],
                "count": 1,
                "has_more": True,
                "next_cursor": "cursor-2",
                "incomplete": True,
            }
        ),
    )

    result = await notion_query_data_source(
        context(selected, tool_name="notion_query_data_source"),
        source_reference("workspace-1"),
        limit=25,
    )

    data = result["results"][0]["data"]
    assert data["records"][0]["reference"].workspace_id == "workspace-1"
    assert data["records"][0]["properties_truncated"] is False
    assert data["incomplete"] is True
    assert audit.await_args.kwargs["external_ref"] == "source-1"
    NotionDataSourceQueryOutput.model_validate(result)


@pytest.mark.parametrize(
    ("tool_name", "call"),
    [
        (
            "notion_read_page",
            lambda ctx: notion_read_page(ctx, page_reference("unselected")),
        ),
        (
            "notion_query_data_source",
            lambda ctx: notion_query_data_source(ctx, source_reference("unselected")),
        ),
    ],
)
async def test_targeted_tools_reject_unselected_workspace(tool_name, call) -> None:
    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await call(context(entry("workspace-1"), tool_name=tool_name))


async def test_search_names_notion_when_no_compatible_context() -> None:
    with pytest.raises(ModelRetry, match="Notion"):
        await notion_search_pages(context(tool_name="notion_search_pages"), query="launch")


def test_tool_contracts_are_code_eligible_typed_and_provider_gated(monkeypatch) -> None:
    assert {definition.name for definition in TOOL_DEFINITIONS} == {
        "notion_search_pages",
        "notion_read_page",
        "notion_query_data_source",
    }
    assert all(definition.code_eligible for definition in TOOL_DEFINITIONS)
    assert all(definition.output_model is not None for definition in TOOL_DEFINITIONS)
    assert all(definition.timeout == 60 for definition in TOOL_DEFINITIONS)

    monkeypatch.setattr(notion_settings, "NOTION_OAUTH_CLIENT_ID", "")
    assert all(not is_tool_allowed(definition, workspace=None) for definition in TOOL_DEFINITIONS)


def test_output_models_forbid_unbounded_extra_provider_fields() -> None:
    with pytest.raises(ValidationError):
        NotionSearchOutput.model_validate(
            {
                "results": [
                    {
                        "provider_key": "notion",
                        "external_id": "workspace-1",
                        "display_name": "Workspace",
                        "status": "success",
                        "data": {
                            "items": [],
                            "count": 0,
                            "has_more": False,
                            "coverage_note": COVERAGE_NOTE,
                            "raw_provider_response": {},
                        },
                    }
                ]
            }
        )


def test_output_models_enforce_public_collection_limits() -> None:
    page = page_reference("workspace-1")
    search_item = {
        "kind": "page",
        "title": notion_text("Launch plan", "page-1", "notion_page"),
        "url": "https://www.notion.so/page-1",
        "last_edited_time": "2026-08-25T12:00:00Z",
        "reference": page,
    }
    with pytest.raises(ValidationError):
        NotionSearchData.model_validate(
            {
                "items": [search_item] * 51,
                "count": 50,
                "has_more": True,
                "coverage_note": COVERAGE_NOTE,
            }
        )

    record = {
        "reference": page,
        "title": notion_text("Launch plan", "page-1", "notion_page"),
        "url": "https://www.notion.so/page-1",
        "last_edited_time": "2026-08-25T12:00:00Z",
        "properties": {},
        "properties_truncated": False,
    }
    with pytest.raises(ValidationError):
        NotionDataSourceQueryData.model_validate(
            {
                "records": [record] * 51,
                "count": 50,
                "has_more": True,
                "incomplete": False,
            }
        )

    with pytest.raises(ValidationError):
        NotionDataSourceQueryData.model_validate(
            {
                "records": [{**record, "properties": {str(index): index for index in range(101)}}],
                "count": 1,
                "has_more": False,
                "incomplete": False,
            }
        )


def test_complete_notion_output_rejects_an_oversized_serialized_result(monkeypatch) -> None:
    selected = entry("workspace-1")
    monkeypatch.setattr("integrations.notion.tools.utils.MAX_NOTION_RESULT_BYTES", 100)

    with pytest.raises(ModelRetry, match="lower maximum result count"):
        bounded_notion_output(
            [
                IntegrationContextResult(
                    entry=selected,
                    status="success",
                    data={"content": "x" * 200},
                )
            ]
        )
