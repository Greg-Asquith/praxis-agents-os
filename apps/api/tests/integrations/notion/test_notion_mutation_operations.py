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
    validate_property_records_against_schema,
)
from integrations.notion.operations.update_page_markdown import (
    MULTIPLE_MATCHES_ERROR_MESSAGE,
    NO_MATCH_ERROR_MESSAGE,
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
    attach_notion_cancellation_evidence,
    failed_notion_mutation_outcome,
    pending_create_page_detail,
    pending_update_content_detail,
    pending_update_properties_detail,
    successful_notion_mutation_outcome,
    terminal_all_applied,
    terminal_all_failed,
    terminal_all_unverified,
)
from services.audit_events import AuditStatus
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
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Launch plan"}]},
            "Status": {"type": status_type, status_type: None},
            "Formula": {"type": "formula", "formula": {"type": "number", "number": 1}},
        },
    }


def data_source_payload(*, in_trash: bool = False) -> dict:
    return {
        "object": "data_source",
        "id": "source-1",
        "in_trash": in_trash,
        "title": [{"plain_text": "Projects"}],
        "properties": {
            "Project": {"type": "title", "title": {}},
            "Status": {"type": "status", "status": {}},
            "Estimate": {"type": "number", "number": {}},
        },
    }


def client_for(handler: Callable[[httpx2.Request], httpx2.Response]):
    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return http_client, NotionClient(token, client=http_client)


async def test_create_page_preparation_reads_live_data_source_schema_and_builds_intent() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=data_source_payload(), request=request)

    scope_entry = entry()
    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_create_page(
            client,
            scope_entry,
            parent_page=None,
            parent_data_source=data_source_reference(),
            title="  Q4 launch  ",
            content_md="# Plan\n",
            properties=[NotionPropertyRecord(name="Status", type="status", value="Planned")],
        )

    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1/data_sources/source-1"
    assert prepared.parent_type == "data_source_id"
    assert prepared.properties == {
        "Project": {"title": [{"type": "text", "text": {"content": "Q4 launch"}}]},
        "Status": {"status": {"name": "Planned"}},
    }
    detail = pending_create_page_detail(scope_entry, prepared)
    assert detail.target.entity_type == "notion_data_source"
    assert detail.target.external_id == "source-1"
    assert detail.target.integration_resource_id == str(scope_entry.integration_resource_id)
    assert detail.intent_groups[0].items[0].fields == {
        "title": "Q4 launch",
        "content_bytes": 7,
        "property_count": 1,
    }


async def test_create_page_preparation_rejects_oversized_complete_request() -> None:
    records = [
        NotionPropertyRecord(
            name=f"Field {index}",
            type="rich_text",
            value="\U0001f680" * 2_000,
        )
        for index in range(50)
    ]
    payload = data_source_payload()
    payload["properties"].update(
        {record.name: {"type": "rich_text", "rich_text": {}} for record in records}
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload, request=request)

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(ModelRetry, match="500000-byte limit"):
            await prepare_create_page(
                client,
                entry(),
                parent_page=None,
                parent_data_source=data_source_reference(),
                title="Launch",
                content_md="x" * 100_000,
                properties=records,
            )


async def test_create_under_page_rejects_additional_properties_before_provider_read() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=page_payload(), request=request)

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(ModelRetry, match="no additional properties"):
            await prepare_create_page(
                client,
                entry(),
                parent_page=page_reference(),
                parent_data_source=None,
                title="Launch",
                content_md="",
                properties=[NotionPropertyRecord(name="Status", type="status", value="Planned")],
            )

    assert calls == 0


@pytest.mark.parametrize(
    ("parent_page", "parent_data_source"),
    [
        (None, None),
        (page_reference(), data_source_reference()),
    ],
)
async def test_create_preparation_requires_exactly_one_parent(
    parent_page: NotionPageReference | None,
    parent_data_source: NotionDataSourceReference | None,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"Unexpected provider request: {request.url}")

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(ModelRetry, match="Choose one"):
            await prepare_create_page(
                client,
                entry(),
                parent_page=parent_page,
                parent_data_source=parent_data_source,
                title="Launch",
                content_md="",
                properties=[],
            )


async def test_create_preparation_rejects_reserved_data_source_title_property() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=data_source_payload(), request=request)

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(ModelRetry, match="title argument"):
            await prepare_create_page(
                client,
                entry(),
                parent_page=None,
                parent_data_source=data_source_reference(),
                title="Launch",
                content_md="",
                properties=[NotionPropertyRecord(name="Project", type="title", value="Other")],
            )


@pytest.mark.parametrize(
    ("title", "content_md", "message"),
    [
        (" ", "", "Page title"),
        ("Launch", "\U0001f680" * (256 * 1024), "Page content"),
    ],
)
async def test_create_preparation_returns_model_retry_for_editable_text_bounds(
    title: str,
    content_md: str,
    message: str,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"Unexpected provider request: {request.url}")

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(ModelRetry, match=message):
            await prepare_create_page(
                client,
                entry(),
                parent_page=page_reference(),
                parent_data_source=None,
                title=title,
                content_md=content_md,
                properties=[],
            )


async def test_property_preparation_reloads_schema_and_revalidates_edited_records() -> None:
    responses = [page_payload(), page_payload(status_type="select")]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=responses.pop(0), request=request)

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


async def test_property_preparation_builds_pending_intent_from_edited_arguments() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=page_payload(), request=request)

    scope_entry = entry()
    http_client, client = client_for(handler)
    async with http_client:
        await prepare_update_page_properties(
            client,
            scope_entry,
            page=page_reference(),
            properties=[NotionPropertyRecord(name="Status", type="status", value="Planned")],
        )
        edited = await prepare_update_page_properties(
            client,
            scope_entry,
            page=page_reference(),
            properties=[NotionPropertyRecord(name="Status", type="status", value="Done")],
        )

    fields = pending_update_properties_detail(scope_entry, edited).intent_groups[0].items[0].fields
    assert fields == {"name": "Status", "type": "status", "value": "Done"}


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (NotionPropertyRecord(name="Missing", type="status", value="Planned"), "no longer"),
        (NotionPropertyRecord(name="Formula", type="number", value="1"), "read-only"),
        (NotionPropertyRecord(name="Status", type="select", value="Planned"), "now has type"),
    ],
)
async def test_property_preparation_rejects_unknown_read_only_and_mismatched_fields(
    record: NotionPropertyRecord,
    message: str,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=page_payload(), request=request)

    http_client, client = client_for(handler)
    async with http_client:
        target = await get_page_mutation_target(client, page_reference())

    with pytest.raises(ModelRetry, match=message):
        validate_property_records_against_schema([record], target)


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


async def test_content_pending_evidence_is_complete_and_bounded() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=page_payload(), request=request)

    old_text = "a" * 1_200
    new_text = "b" * 1_100
    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_update_page_markdown(
            client,
            entry(),
            page=page_reference(),
            replacements=[
                NotionReplacementRecord(
                    old_text=old_text,
                    new_text=new_text,
                    replace_all="yes",
                )
            ],
        )

    fields = pending_update_content_detail(entry(), prepared).intent_groups[0].items[0].fields
    assert fields == {
        "old_text": old_text[:1_000],
        "new_text": new_text[:1_000],
        "old_text_length": 1_200,
        "new_text_length": 1_100,
        "replace_all": "yes",
    }


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


async def test_revoked_credentials_fail_during_preparation() -> None:
    forces: list[bool] = []

    async def revoked_token(force: bool) -> str:
        forces.append(force)
        return "fresh" if force else "stale"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = NotionClient(revoked_token, client=http_client)
        with pytest.raises(IntegrationAuthError):
            await prepare_update_page_markdown(
                client,
                entry(),
                page=page_reference(),
                replacements=[
                    NotionReplacementRecord(old_text="Draft", new_text="Final", replace_all="no")
                ],
            )

    assert forces == [False, True]


async def test_malformed_live_schema_fails_closed() -> None:
    payload = page_payload()
    payload["properties"] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload, request=request)

    http_client, client = client_for(handler)
    async with http_client:
        with pytest.raises(IntegrationValidationError, match="property schema"):
            await get_page_mutation_target(client, page_reference())


@pytest.mark.parametrize("malformation", ["missing_object", "wrong_object", "missing_in_trash"])
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


def test_notion_write_binding_requires_writable_resources() -> None:
    assert NOTION_WRITE_BINDING.requires_write is True
    assert NOTION_WRITE_BINDING.provider_keys == frozenset({"notion"})


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
        return httpx2.Response(200, json=page_payload(), request=request)

    http_client, client = client_for(handler)
    async with http_client:
        prepared = await prepare_update_page_properties(
            client,
            entry(),
            page=page_reference(),
            properties=[NotionPropertyRecord(name="Status", type="status", value="Done")],
        )
        result = await update_page_properties(client, prepared=prepared)

    assert [request.method for request in requests] == ["GET", "PATCH"]
    assert requests[1].url.path == "/v1/pages/page-1"
    assert json.loads(requests[1].content) == {
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
    ("provider_message", "expected_message"),
    [
        ("old_str could not find a match", NO_MATCH_ERROR_MESSAGE),
        ("old_str matches more than one location", MULTIPLE_MATCHES_ERROR_MESSAGE),
    ],
)
async def test_content_validation_errors_map_to_safe_specific_messages(
    provider_message: str,
    expected_message: str,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "PATCH":
            return httpx2.Response(
                400,
                json={"code": "validation_error", "message": provider_message},
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
                NotionReplacementRecord(old_text="Draft", new_text="Final", replace_all="no")
            ],
        )
        with pytest.raises(IntegrationValidationError) as exc_info:
            await update_page_markdown(client, prepared=prepared)

    assert exc_info.value.user_message == expected_message
    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.REJECTED
    assert provider_message not in exc_info.value.user_message


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
        return httpx2.Response(200, json=page_payload(), request=request)

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
        {
            "object": "page",
            "id": "different-page",
            "in_trash": False,
            "url": "https://www.notion.so/different-page",
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
        return httpx2.Response(503, json={}, request=request)

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


def test_terminal_evidence_builders_align_every_intent_and_effect() -> None:
    pending = pending_update_content_detail(
        entry(),
        SimpleNamespace(
            page=SimpleNamespace(
                entity_type="notion_page",
                external_id="page-1",
                display_name="Launch plan",
            ),
            replacements=(
                SimpleNamespace(old_text="A", new_text="B", replace_all="no"),
                SimpleNamespace(old_text="C", new_text="D", replace_all="yes"),
            ),
        ),
    )

    applied = terminal_all_applied(pending, external_ref="page-1")
    failed = terminal_all_failed(pending, error_code="validation_error")
    unverified = terminal_all_unverified(pending, error_code="timeout")

    assert applied.intent_counts.applied == applied.effect_counts.applied == 2
    assert failed.intent_counts.failed == failed.effect_counts.failed == 2
    assert unverified.intent_counts.unverified == unverified.effect_counts.unverified == 2
    assert [outcome.intent_index for outcome in applied.outcome_groups[0].outcomes] == [0, 1]
    assert {
        effect.external_ref
        for outcome in applied.outcome_groups[0].outcomes
        for effect in outcome.effects
    } == {"page-1"}


def test_failure_outcomes_keep_only_stable_public_error_evidence() -> None:
    pending = pending_create_page_detail(
        entry(),
        SimpleNamespace(
            parent=SimpleNamespace(
                entity_type="notion_page",
                external_id="page-1",
                display_name="Launch plan",
            ),
            title="Child page",
            content_md="",
            property_count=0,
        ),
    )
    error = IntegrationTimeoutError(
        "Provider message that must stay private",
        provider_key="notion",
        operation="create_page",
        failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
    )

    outcome = failed_notion_mutation_outcome(
        pending,
        {"title": "Child page"},
        error,
        operation="create_page",
    )

    assert outcome.status is AuditStatus.UNVERIFIED
    assert outcome.value == {
        "title": "Child page",
        "outcome": "unverified",
        "error_code": "timeout",
    }
    assert outcome.unverified_result == outcome.value
    assert "Provider message" not in str(outcome.value)

    rejected = IntegrationPermissionError(
        "Provider capability message that must stay private",
        provider_key="notion",
        operation="create_page",
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )
    rejected_outcome = failed_notion_mutation_outcome(
        pending,
        {"title": "Child page"},
        rejected,
        operation="create_page",
    )
    assert rejected_outcome.status is AuditStatus.FAILURE
    assert rejected_outcome.value["outcome"] == "failed"
    assert rejected_outcome.value["error_code"] == "permission_denied"
    assert rejected_outcome.unverified_result is None
    assert rejected_outcome.operation_detail.intent_counts.failed == 1


def test_success_and_cancellation_outcomes_use_exact_terminal_evidence() -> None:
    pending = pending_create_page_detail(
        entry(),
        SimpleNamespace(
            parent=SimpleNamespace(
                entity_type="notion_page",
                external_id="page-1",
                display_name="Launch plan",
            ),
            title="Child page",
            content_md="",
            property_count=0,
        ),
    )
    success = successful_notion_mutation_outcome(
        pending,
        {"id": "created-page"},
        external_ref="created-page",
        single_item=True,
    )
    cancellation = asyncio.CancelledError()
    cancellation.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
    attach_notion_cancellation_evidence(
        cancellation,
        pending,
        operation="create_page",
    )

    assert success.status is AuditStatus.SUCCESS
    assert success.external_ref == "created-page"
    assert success.operation_detail.intent_counts.applied == 1
    assert cancellation.operation_detail.intent_counts.unverified == 1
    assert cancellation.operation_detail.effect_counts.unverified == 1
