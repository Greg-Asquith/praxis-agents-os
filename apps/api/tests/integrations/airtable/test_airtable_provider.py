"""Airtable discovery and REST operation contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2

from integrations.airtable.client import AirtableClient
from integrations.airtable.discover_resources import discover_resources
from integrations.airtable.operations.create_record import create_record
from integrations.airtable.operations.get_record import get_record
from integrations.airtable.operations.list_records import list_records
from integrations.airtable.operations.update_record import update_record
from integrations.airtable.tools.utils import airtable_client
from services.integrations import http as integration_http
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.providers_view import list_providers


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
