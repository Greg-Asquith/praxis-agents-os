"""Notion mutation preparation and pending-evidence contracts."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.notion.client import NotionClient
from integrations.notion.operations.create_page import create_page, prepare_create_page
from integrations.notion.operations.properties import (
    get_page_mutation_target,
)
from integrations.notion.operations.update_page_markdown import (
    prepare_update_page_markdown,
    update_page_markdown,
)
from integrations.notion.operations.update_page_properties import (
    prepare_update_page_properties,
    update_page_properties,
)
from integrations.notion.references import NotionDataSourceReference, NotionPageReference
from integrations.notion.tools.mutations import NotionPropertyRecord, NotionReplacementRecord
from integrations.notion.tools.utils import (
    NOTION_WRITE_BINDING,
    pending_update_properties_detail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.execution import _run_authorized_entries


async def token(force: bool) -> str:
    return "fresh-token" if force else "access-token"


def entry(workspace_id: str = "workspace-1") -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="notion",
        resource_type="notion_workspace",
        external_id=workspace_id,
        display_name="Example workspace",
        connection_id=uuid4(),
        connection_label="Notion",
        connection_status="active",
        write_allowed=True,
    )


def page_reference(workspace_id: str = "workspace-1") -> NotionPageReference:
    return NotionPageReference(
        workspace_id=workspace_id,
        page_id="page-1",
        label="Launch plan",
        scope_label="Example workspace",
    )


def data_source_reference(workspace_id: str = "workspace-1") -> NotionDataSourceReference:
    return NotionDataSourceReference(
        workspace_id=workspace_id,
        data_source_id="source-1",
        label="Projects",
        scope_label="Example workspace",
    )


def page_payload(*, in_trash: bool = False, status_type: str = "status") -> dict:
    return {
        "object": "page",
        "id": "page-1",
        "in_trash": in_trash,
        "url": "https://www.notion.so/page-1",
        "last_edited_time": "2026-09-01T09:30:00.000Z",
        "parent": {"type": "data_source_id", "data_source_id": "source-1"},
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Launch plan"}]},
            "Status": {"type": status_type, status_type: None},
            "Formula": {"type": "formula", "formula": {"type": "number", "number": 1}},
        },
    }


def data_source_payload(*, in_trash: bool = False, status_type: str = "status") -> dict:
    return {
        "object": "data_source",
        "id": "source-1",
        "in_trash": in_trash,
        "title": [{"plain_text": "Projects"}],
        "properties": {
            "Project": {"type": "title", "title": {}},
            "Status": {
                "type": status_type,
                status_type: {
                    "options": [
                        {"name": "Planned"},
                        {"name": "Done"},
                        {"name": "Needs review, legal"},
                    ],
                },
            },
            "Estimate": {"type": "number", "number": {}},
            "Priority": {
                "type": "select",
                "select": {"options": [{"name": "High"}, {"name": "Low"}]},
            },
            "Tags": {
                "type": "multi_select",
                "multi_select": {"options": [{"name": "API"}, {"name": "Documentation"}]},
            },
        },
    }


def client_for(handler: Callable[[httpx2.Request], httpx2.Response]):
    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return http_client, NotionClient(token, client=http_client)


async def test_property_preparation_reloads_schema_and_revalidates_edited_records() -> None:
    responses = [data_source_payload(), data_source_payload(status_type="select")]

    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = page_payload() if request.url.path.endswith("/pages/page-1") else responses.pop(0)
        return httpx2.Response(200, json=payload, request=request)

    record = NotionPropertyRecord(name="Status", type="status", value="Planned")
    http_client, client = client_for(handler)
    async with http_client:
        first = await prepare_update_page_properties(
            client,
            entry(),
            page=page_reference(),
            properties=[record],
        )
        with pytest.raises(ModelRetry, match="now has type 'select'"):
            await prepare_update_page_properties(
                client,
                entry(),
                page=page_reference(),
                properties=[record],
            )

    detail = pending_update_properties_detail(entry(), first)
    assert detail.intent_groups[0].items[0].fields == {
        "name": "Status",
        "type": "status",
        "value": "Planned",
    }
    assert responses == []


async def test_property_preparation_rejects_option_removed_during_approval() -> None:
    schema_reads = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal schema_reads
        if request.url.path.endswith("/pages/page-1"):
            return httpx2.Response(200, json=page_payload(), request=request)
        payload = data_source_payload()
        schema_reads += 1
        if schema_reads == 2:
            payload["properties"]["Status"]["status"]["options"] = [{"name": "Planned"}]
        return httpx2.Response(200, json=payload, request=request)

    record = NotionPropertyRecord(name="Status", type="status", value="Done")
    http_client, client = client_for(handler)
    async with http_client:
        await prepare_update_page_properties(
            client,
            entry(),
            page=page_reference(),
            properties=[record],
        )
        with pytest.raises(ModelRetry, match="does not contain option 'Done'"):
            await prepare_update_page_properties(
                client,
                entry(),
                page=page_reference(),
                properties=[record],
            )


async def test_content_preparation_rejects_trashed_page_before_pending_evidence() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=page_payload(in_trash=True), request=request)

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(ModelRetry, match="in the trash"):
            await prepare_update_page_markdown(
                client,
                entry(),
                page=page_reference(),
                replacements=[
                    NotionReplacementRecord(old_text="Draft", new_text="Final", replace_all="no")
                ],
            )


async def test_cross_context_reference_is_rejected_without_provider_call() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=page_payload(), request=request)

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(ModelRetry, match="active integration context"):
            await prepare_update_page_properties(
                client,
                entry("workspace-1"),
                page=page_reference("workspace-2"),
                properties=[NotionPropertyRecord(name="Status", type="status", value="Planned")],
            )

    assert calls == 0


@pytest.mark.parametrize(
    "malformation",
    [
        "missing_object",
    ],
)
async def test_malformed_live_target_identity_fails_closed(malformation: str) -> None:
    payload = page_payload()
    if malformation == "missing_object":
        payload.pop("object")
    elif malformation == "wrong_object":
        payload["object"] = "data_source"
    else:
        payload.pop("in_trash")

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload, request=request)

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(IntegrationValidationError):
            await get_page_mutation_target(client, page_reference())


async def test_notion_write_binding_denies_read_only_entry_without_provider_call(
    monkeypatch,
) -> None:
    read_only_entry = replace(entry(), write_allowed=False)
    ctx = SimpleNamespace()
    operation = AsyncMock()
    denial = AsyncMock()
    monkeypatch.setattr(
        "services.integrations.operations._resolve_dispatched_integration_definition",
        lambda _ctx: SimpleNamespace(integration_binding=NOTION_WRITE_BINDING),
    )
    monkeypatch.setattr("services.integrations.operations.record_integration_write_denial", denial)

    results = await _run_authorized_entries(
        ctx,
        binding=NOTION_WRITE_BINDING,
        selected=((read_only_entry, None),),
        operation=operation,
    )

    operation.assert_not_awaited()
    denial.assert_awaited_once_with(ctx, read_only_entry)
    assert results[0].status == "error"
    assert results[0].error_code == "write_not_permitted"


async def test_create_page_sends_only_the_documented_synchronous_mutation() -> None:
    created_id = str(uuid4())
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx2.Response(200, json=page_payload(), request=request)
        return httpx2.Response(
            200,
            json={
                "object": "page",
                "id": created_id,
                "in_trash": False,
                "url": f"https://www.notion.so/{created_id}",
                "last_edited_time": "2026-09-01T10:00:00.000Z",
            },
            request=request,
        )

    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_create_page(
            client,
            entry(),
            parent_page=page_reference(),
            parent_data_source=None,
            title="Launch plan",
            content_md="# Launch\n",
            properties=[],
        )
        result = await create_page(client, prepared=prepared)

    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[1].url.path == "/v1/pages"
    assert json.loads(requests[1].content) == {
        "parent": {"type": "page_id", "page_id": "page-1"},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": "Launch plan"}}]}},
        "markdown": "# Launch\n",
    }
    assert "allow_async" not in json.loads(requests[1].content)
    assert "children" not in json.loads(requests[1].content)
    assert result == {
        "id": created_id,
        "url": f"https://www.notion.so/{created_id}",
        "last_edited_time": "2026-09-01T10:00:00.000Z",
        "title": "Launch plan",
    }


async def test_update_page_properties_sends_schema_validated_values_once() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        payload = (
            data_source_payload()
            if request.url.path.endswith("/data_sources/source-1")
            else page_payload()
        )
        return httpx2.Response(200, json=payload, request=request)

    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_update_page_properties(
            client,
            entry(),
            page=page_reference(),
            properties=[NotionPropertyRecord(name="Status", type="status", value="Done")],
        )
        result = await update_page_properties(client, prepared=prepared)

    assert [request.method for request in requests] == ["GET", "GET", "PATCH"]
    assert requests[2].url.path == "/v1/pages/page-1"
    assert json.loads(requests[2].content) == {
        "properties": {"Status": {"status": {"name": "Done"}}}
    }
    assert result["id"] == "page-1"


async def test_update_page_markdown_sends_exact_replacements_and_reads_edit_time() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "PATCH":
            return httpx2.Response(
                200,
                json={
                    "object": "page_markdown",
                    "id": "page-1",
                    "markdown": "Final plan",
                    "truncated": False,
                    "unknown_block_ids": [],
                },
                request=request,
            )
        return httpx2.Response(200, json=page_payload(), request=request)

    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_update_page_markdown(
            client,
            entry(),
            page=page_reference(),
            replacements=[
                NotionReplacementRecord(
                    old_text="Draft plan",
                    new_text="Final plan",
                    replace_all="no",
                )
            ],
        )
        result = await update_page_markdown(client, prepared=prepared)

    assert [request.method for request in requests] == ["GET", "PATCH", "GET"]
    assert requests[1].url.path == "/v1/pages/page-1/markdown"
    assert json.loads(requests[1].content) == {
        "type": "update_content",
        "update_content": {
            "content_updates": [
                {
                    "old_str": "Draft plan",
                    "new_str": "Final plan",
                    "replace_all_matches": False,
                }
            ]
        },
    }
    assert "allow_async" not in json.loads(requests[1].content)
    assert "allow_deleting_content" not in json.loads(requests[1].content)
    assert "insert_content" not in json.loads(requests[1].content)
    assert result == {
        "id": "page-1",
        "applied_replacements": 1,
        "page_truncated": False,
        "last_edited_time": "2026-09-01T09:30:00.000Z",
    }


@pytest.mark.parametrize(
    ("status_code", "error_type", "disposition"),
    [
        (403, IntegrationPermissionError, IntegrationFailureDisposition.REJECTED),
        (429, IntegrationRateLimitError, IntegrationFailureDisposition.AMBIGUOUS),
    ],
)
async def test_mutation_errors_retain_definitive_or_ambiguous_disposition(
    status_code: int,
    error_type: type[Exception],
    disposition: IntegrationFailureDisposition,
) -> None:
    patch_calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal patch_calls
        if request.method == "PATCH":
            patch_calls += 1
            return httpx2.Response(status_code, json={}, request=request)
        payload = (
            data_source_payload()
            if request.url.path.endswith("/data_sources/source-1")
            else page_payload()
        )
        return httpx2.Response(200, json=payload, request=request)

    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_update_page_properties(
            client,
            entry(),
            page=page_reference(),
            properties=[NotionPropertyRecord(name="Status", type="status", value="Done")],
        )
        with pytest.raises(error_type) as exc_info:
            await update_page_properties(client, prepared=prepared)

    assert exc_info.value.failure_disposition is disposition
    assert patch_calls == 1


async def test_mutation_credential_failure_is_not_dispatched() -> None:
    async def unavailable_token(force: bool) -> str:
        raise IntegrationAuthError("Credential unavailable", provider_key="notion")

    prepared = SimpleNamespace(
        page=SimpleNamespace(external_id="page-1"),
        properties={"Status": {"status": {"name": "Done"}}},
    )
    client = NotionClient(unavailable_token)
    with pytest.raises(IntegrationAuthError) as exc_info:
        await update_page_properties(client, prepared=prepared)

    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED


async def test_mutation_timeout_is_ambiguous_and_not_retried() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        raise httpx2.ReadTimeout("timed out", request=request)

    prepared = SimpleNamespace(
        page=SimpleNamespace(external_id="page-1"),
        properties={"Status": {"status": {"name": "Done"}}},
    )
    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(IntegrationTimeoutError) as exc_info:
            await update_page_properties(client, prepared=prepared)

    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
    assert calls == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "page", "in_trash": False},
        {
            "object": "page",
            "id": "page-1",
            "in_trash": True,
            "url": "https://www.notion.so/page-1",
            "last_edited_time": "2026-09-01T10:00:00.000Z",
        },
    ],
)
async def test_malformed_or_unverifiable_success_is_ambiguous(payload: dict) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload, request=request)

    prepared = SimpleNamespace(
        page=SimpleNamespace(external_id="page-1"),
        properties={"Status": {"status": {"name": "Done"}}},
    )
    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(IntegrationValidationError) as exc_info:
            await update_page_properties(client, prepared=prepared)

    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS


async def test_content_follow_up_read_failure_keeps_confirmed_mutation_applied() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "PATCH":
            return httpx2.Response(
                200,
                json={
                    "object": "page_markdown",
                    "id": "page-1",
                    "markdown": "Final",
                    "truncated": False,
                    "unknown_block_ids": [],
                },
                request=request,
            )
        return httpx2.Response(400, json={}, request=request)

    prepared = SimpleNamespace(
        page=SimpleNamespace(external_id="page-1"),
        replacements=(SimpleNamespace(old_text="Draft", new_text="Final", replace_all="no"),),
    )
    http_client, client = client_for(handler)
    async with http_client:
        result = await update_page_markdown(client, prepared=prepared)

    assert result["last_edited_time"] is None
    assert result["applied_replacements"] == 1


async def test_content_follow_up_cancellation_keeps_confirmed_mutation_applied() -> None:
    get_calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal get_calls
        if request.method == "PATCH":
            return httpx2.Response(
                200,
                json={
                    "object": "page_markdown",
                    "id": "page-1",
                    "markdown": "Final",
                    "truncated": False,
                    "unknown_block_ids": [],
                },
                request=request,
            )
        get_calls += 1
        if get_calls == 1:
            return httpx2.Response(200, json=page_payload(), request=request)
        raise asyncio.CancelledError

    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_update_page_markdown(
            client,
            entry(),
            page=page_reference(),
            replacements=[
                NotionReplacementRecord(old_text="Draft", new_text="Final", replace_all="no")
            ],
        )
        result = await update_page_markdown(client, prepared=prepared)

    assert get_calls == 2
    assert result["last_edited_time"] is None
    assert result["applied_replacements"] == 1
