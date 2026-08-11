"""Airtable discovery and REST operation contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationNotFoundError
from integrations.airtable.client import AirtableClient
from integrations.airtable.discover_resources import discover_resources
from integrations.airtable.entity_resolvers.record import (
    resolve_airtable_records,
    search_airtable_records,
)
from integrations.airtable.operations.create_record import create_record
from integrations.airtable.operations.get_record import get_record
from integrations.airtable.operations.list_records import list_records
from integrations.airtable.operations.update_record import update_record
from integrations.airtable.references import AirtableRecordReference
from integrations.airtable.tools import TOOL_DEFINITIONS
from integrations.airtable.tools.get_record import airtable_get_record
from integrations.airtable.tools.list_records import airtable_list_records
from integrations.airtable.tools.update_record import airtable_update_record
from integrations.airtable.tools.utils import airtable_client
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations import http as integration_http
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.providers_view import list_providers


@pytest.fixture(autouse=True)
def _loaded_airtable_tool_definitions(monkeypatch):
    for definition in TOOL_DEFINITIONS:
        monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)


def test_manifest_declares_and_exposes_discovery_and_pat_scope_help(monkeypatch) -> None:
    from integrations.airtable import PROVIDER

    manifest = PROVIDER.manifest
    assert manifest.requires_discovery is True
    assert manifest.resource_types == ("airtable_base",)
    assert "data.records:read" in manifest.connect_help
    assert "data.records:write" in manifest.connect_help
    assert "schema.bases:read" in manifest.connect_help
    monkeypatch.setitem(PROVIDER_MANIFESTS, "airtable", manifest)
    provider = next(item for item in list_providers() if item.provider_key == "airtable")
    assert provider.connect_help == manifest.connect_help


def test_record_reference_identity_is_provider_owned_and_ignores_display_hints() -> None:
    resource_id = uuid4()
    original = AirtableRecordReference(
        integration_resource_id=resource_id,
        external_id="rec-one",
        table="Contacts",
        label="Original label",
    )
    renamed = original.model_copy(update={"label": "Renamed contact"})
    other_table = original.model_copy(update={"table": "Orders"})

    assert original.identity() == renamed.identity()
    assert original.identity() != other_table.identity()


async def test_discovery_paginates_and_maps_write_permissions(monkeypatch) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer pat"
        if request.url.params.get("offset") == "next-page":
            return httpx2.Response(
                200,
                json={
                    "bases": [
                        {"id": "app-read", "name": "Read", "permissionLevel": "read"},
                        {"id": "app-comment", "name": "Comment", "permissionLevel": "comment"},
                    ]
                },
                request=request,
            )
        return httpx2.Response(
            200,
            json={
                "bases": [
                    {"id": "app-edit", "name": "Edit", "permissionLevel": "edit"},
                    {"id": "app-create", "name": "Create", "permissionLevel": "create"},
                ],
                "offset": "next-page",
            },
            request=request,
        )

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=httpx2.MockTransport(handler)),
    )

    resources = tuple(await discover_resources("pat"))

    assert [item.external_id for item in resources] == [
        "app-edit",
        "app-create",
        "app-read",
        "app-comment",
    ]
    assert [item.writable for item in resources] == [True, True, False, False]
    assert resources[0].permissions_metadata == {"permission_level": "edit"}
    assert requests[1].url.params["offset"] == "next-page"


async def test_list_and_get_records_frame_provider_text() -> None:
    list_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal list_request
        if request.url.path.endswith("/rec-one"):
            return httpx2.Response(
                200,
                json={"id": "rec-one", "fields": {"Name": "One"}},
                request=request,
            )
        list_request = request
        return httpx2.Response(
            200,
            json={
                "records": [
                    {
                        "id": "rec-one",
                        "createdTime": "2026-07-22T10:00:00.000Z",
                        "fields": {"Name": "One", "Tags": ["A", "B"]},
                    }
                ]
            },
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = AirtableClient(_static_token, client=http_client)
        listed = await list_records(
            client,
            base_id="app-one",
            table="Table / One",
            view="Grid",
            filter_by_formula="{Active}=1",
            max_records=250,
        )
        fetched = await get_record(
            client,
            base_id="app-one",
            table="Table / One",
            record_id="rec-one",
        )

    assert listed["total"] == 1
    assert list_request is not None
    assert list_request.url.params["maxRecords"] == "100"
    assert list_request.url.params["view"] == "Grid"
    assert list_request.url.params["filterByFormula"] == "{Active}=1"
    assert listed["records"][0]["fields"]["Name"].content == "One"
    assert listed["records"][0]["fields"]["Tags"][1].source_ref == "rec-one"
    assert fetched["fields"]["Name"].content == "One"


async def test_create_and_update_return_record_ids() -> None:
    methods: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        methods.append(request.method)
        record_id = "rec-created" if request.method == "POST" else "rec-updated"
        return httpx2.Response(200, json={"id": record_id}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = AirtableClient(_static_token, client=http_client)
        created = await create_record(
            client,
            base_id="app-one",
            table="Contacts",
            fields={"Name": "Ada"},
        )
        updated = await update_record(
            client,
            base_id="app-one",
            table="Contacts",
            record_id="rec-created",
            fields={"Name": "Grace"},
        )

    assert methods == ["POST", "PATCH"]
    assert created == {"record_id": "rec-created"}
    assert updated == {"record_id": "rec-updated"}


async def test_record_hydration_omits_stale_item_without_aborting_batch(monkeypatch) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="airtable",
        resource_type="airtable_base",
        external_id="app-one",
        display_name="Base",
        connection_id=uuid4(),
        connection_label="Airtable",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
    )
    foreign_resource_id = uuid4()

    async def record(_client, *, record_id, **_kwargs):
        if record_id == "rec-deleted":
            raise IntegrationNotFoundError("Record not found", provider_key="airtable")
        return {"record_id": record_id, "fields": {"Name": record_id}}

    monkeypatch.setattr(
        "integrations.airtable.entity_resolvers.record.airtable_client_for_principal",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr("integrations.airtable.entity_resolvers.record.get_record", record)

    choices = await resolve_airtable_records(
        ctx,
        [
            AirtableRecordReference(
                integration_resource_id=entry.integration_resource_id,
                external_id=record_id,
                table="Contacts",
                label=record_id,
                scope_label=entry.display_name,
            )
            for record_id in ("rec-first", "rec-deleted", "rec-last")
        ]
        + [
            AirtableRecordReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="rec-wrong-table",
                table="Orders",
                label="Wrong table",
            ),
            AirtableRecordReference(
                integration_resource_id=foreign_resource_id,
                external_id="rec-foreign-base",
                table="Contacts",
                label="Foreign base",
            ),
        ],
        {"table": "Contacts"},
    )

    assert [choice.value["external_id"] for choice in choices] == [
        "rec-first",
        "rec-last",
    ]


async def test_record_search_bounds_pagination_and_filters_active_scope(monkeypatch) -> None:
    active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="airtable",
        resource_type="airtable_base",
        external_id="app-active",
        display_name="Active base",
        connection_id=uuid4(),
        connection_label="Airtable",
        connection_status="active",
        write_allowed=True,
    )
    second_active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="airtable",
        resource_type="airtable_base",
        external_id="app-second",
        display_name="Second base",
        connection_id=uuid4(),
        connection_label="Airtable",
        connection_status="active",
        write_allowed=True,
    )
    incompatible = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
        display_name="Mailbox",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active, second_active, incompatible)),
    )
    client_factory = AsyncMock(return_value=object())
    provider_list = AsyncMock(
        return_value={
            "records": [
                {"record_id": f"rec-{index}", "fields": {"Name": f"Match {index}"}}
                for index in range(100)
            ]
        }
    )
    monkeypatch.setattr(
        "integrations.airtable.entity_resolvers.record.airtable_client_for_principal",
        client_factory,
    )
    monkeypatch.setattr(
        "integrations.airtable.entity_resolvers.record.list_records",
        provider_list,
    )

    page = await search_airtable_records(ctx, "match", {"table": "Contacts"}, 20, "95")

    assert len(page.choices) == 5
    assert page.next_cursor is None
    assert [call.kwargs["entry"] for call in client_factory.await_args_list] == [
        active,
        second_active,
    ]
    assert [call.kwargs["base_id"] for call in provider_list.await_args_list] == [
        "app-active",
        "app-second",
    ]
    assert all(call.kwargs["table"] == "Contacts" for call in provider_list.await_args_list)
    assert all(call.kwargs["max_records"] == 100 for call in provider_list.await_args_list)


async def test_list_records_attaches_each_base_scope_to_returned_references(monkeypatch) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="airtable",
            resource_type="airtable_base",
            external_id=base_id,
            display_name=f"Base {base_id}",
            connection_id=uuid4(),
            connection_label="Airtable",
            connection_status="active",
            write_allowed=True,
        )
        for base_id in ("app-one", "app-two")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries)),
        tool_name="airtable_list_records",
    )

    async def provider_list(_client, *, base_id, **_kwargs):
        return {"records": [{"record_id": f"rec-{base_id}", "fields": {"Name": base_id}}]}

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.airtable.tools.list_records.airtable_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr("integrations.airtable.tools.list_records.list_records", provider_list)
    monkeypatch.setattr(
        "integrations.airtable.tools.list_records.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await airtable_list_records(ctx, "Contacts")

    references = [item["data"]["records"][0]["reference"] for item in result["results"]]
    assert [reference.integration_resource_id for reference in references] == [
        entry.integration_resource_id for entry in entries
    ]
    assert [reference.external_id for reference in references] == [
        "rec-app-one",
        "rec-app-two",
    ]


@pytest.mark.parametrize(
    ("tool", "module", "operation_name"),
    [
        (airtable_get_record, "get_record", "get_record"),
        (airtable_update_record, "update_record", "update_record"),
    ],
)
async def test_record_tools_target_only_the_referenced_base(
    monkeypatch,
    tool,
    module,
    operation_name,
) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="airtable",
            resource_type="airtable_base",
            external_id=base_id,
            display_name=f"Base {base_id}",
            connection_id=uuid4(),
            connection_label="Airtable",
            connection_status="active",
            write_allowed=True,
        )
        for base_id in ("app-one", "app-two")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries)),
        tool_name=f"airtable_{operation_name}",
    )
    provider_operation = AsyncMock(return_value={"record_id": "rec-selected"})

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    module_path = f"integrations.airtable.tools.{module}"
    monkeypatch.setattr(f"{module_path}.airtable_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(f"{module_path}.{operation_name}", provider_operation)
    monkeypatch.setattr(f"{module_path}.run_audited_integration_operation", passthrough_audit)
    reference = AirtableRecordReference(
        integration_resource_id=entries[1].integration_resource_id,
        external_id="rec-selected",
        table="Contacts",
        label="Selected",
    )

    if tool is airtable_update_record:
        result = await tool(ctx, "Contacts", reference, {"Status": "Done"})
    else:
        result = await tool(ctx, "Contacts", reference)

    assert len(result["results"]) == 1
    assert result["results"][0]["integration_resource_id"] == entries[1].integration_resource_id
    assert provider_operation.await_args.kwargs["base_id"] == "app-two"
    assert provider_operation.await_args.kwargs["record_id"] == "rec-selected"


async def test_update_record_rejects_table_reference_mismatch_before_dispatch(monkeypatch) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="airtable",
        resource_type="airtable_base",
        external_id="app-one",
        display_name="Base",
        connection_id=uuid4(),
        connection_label="Airtable",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="airtable_update_record",
    )
    provider_update = AsyncMock()
    monkeypatch.setattr("integrations.airtable.tools.update_record.update_record", provider_update)

    with pytest.raises(ModelRetry, match="table changed"):
        await airtable_update_record(
            ctx,
            "Contacts",
            AirtableRecordReference(
                integration_resource_id=entry.integration_resource_id,
                external_id="rec-one",
                table="Orders",
                label="Order",
            ),
            {"Status": "Done"},
        )

    provider_update.assert_not_awaited()


async def test_update_record_accepts_cosmetic_table_name_differences(monkeypatch) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="airtable",
        resource_type="airtable_base",
        external_id="app-one",
        display_name="Base",
        connection_id=uuid4(),
        connection_label="Airtable",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="airtable_update_record",
    )
    provider_update = AsyncMock(return_value={"record_id": "rec-one"})

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.airtable.tools.update_record.airtable_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr("integrations.airtable.tools.update_record.update_record", provider_update)
    monkeypatch.setattr(
        "integrations.airtable.tools.update_record.run_audited_integration_operation",
        passthrough_audit,
    )

    await airtable_update_record(
        ctx,
        "  contacts  ",
        AirtableRecordReference(
            integration_resource_id=entry.integration_resource_id,
            external_id="rec-one",
            table="Contacts",
            label="Contact",
        ),
        {"Status": "Done"},
    )

    assert provider_update.await_args.kwargs["table"] == "Contacts"


async def test_airtable_rate_limit_honors_retry_after(monkeypatch) -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(
            429 if attempts == 1 else 200,
            headers={"Retry-After": "1"} if attempts == 1 else {},
            json={"records": []},
            request=request,
        )

    sleep = AsyncMock()
    monkeypatch.setattr(integration_http.asyncio, "sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        payload = await AirtableClient(_static_token, client=client).get(
            "app/Table",
            operation="list_records",
        )

    assert payload == {"records": []}
    assert attempts == 2
    sleep.assert_awaited_once_with(1.0)


async def test_each_context_entry_resolves_its_own_connection_secret(monkeypatch) -> None:
    credential_ids = {uuid4(): uuid4(), uuid4(): uuid4()}
    credentials = {
        credential_id: SimpleNamespace(
            deleted=False,
            auth_mode="api_key",
            secret_provider="local",  # noqa: S106 - inert test reference metadata
            secret_name=f"secret-{index}",
            secret_version="1",  # noqa: S106 - inert test reference metadata
        )
        for index, credential_id in enumerate(credential_ids.values(), start=1)
    }
    db = SimpleNamespace(get=AsyncMock(side_effect=lambda _model, key: credentials[key]))
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            db=db,
            user=SimpleNamespace(id=uuid4()),
            workspace=SimpleNamespace(id=uuid4()),
        )
    )

    async def usable_credential(_db, *, connection_id, **_kwargs):
        return credentials[credential_ids[connection_id]]

    async def secret(_db, reference, **_kwargs):
        return f"token-for-{reference.name}"

    seen_authorizations: list[str] = []

    async def request(_method, url, **kwargs):
        seen_authorizations.append(kwargs["headers"]["Authorization"])
        return httpx2.Response(200, json={"url": url}, request=httpx2.Request("GET", url))

    monkeypatch.setattr(
        "integrations.airtable.tools.utils.get_usable_connection_credential",
        usable_credential,
    )
    monkeypatch.setattr("integrations.airtable.tools.utils.resolve_secret", secret)
    monkeypatch.setattr("integrations.airtable.client.request_with_retries", request)

    for connection_id in credential_ids:
        entry = ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="airtable",
            resource_type="airtable_base",
            external_id="app-one",
            display_name="Base",
            connection_id=connection_id,
            connection_label="Connection",
            connection_status="active",
            write_allowed=True,
        )
        client = await airtable_client(ctx, entry)
        await client.get("app-one/Table", operation="list_records")

    assert seen_authorizations == [
        "Bearer token-for-secret-1",
        "Bearer token-for-secret-2",
    ]


async def _static_token() -> str:
    return "pat"
