"""Link resolution, library boundaries, and connection-level request limits."""

import asyncio
from base64 import urlsafe_b64decode
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from integrations.sharepoint.operations.resolve_link import resolve_link
from integrations.sharepoint.operations.utils import ITEM_SELECT
from integrations.sharepoint.tools.open_link import DEFINITION, sharepoint_open_link
from integrations.sharepoint.tools.schemas import SharePointLinkOutput
from services.agents.runtime.code_mode.stubs import render_tool_stub
from services.agents.runtime.tools.contract import validate_definition
from tests.integrations.sharepoint.support import (
    DOWNLOAD_URL,
    context,
    entry,
    file_metadata,
    fixture,
    graph,
)

BASE = "https://example.sharepoint.com/sites/Finance/Documents"
DIRECT = BASE + "/Quarterly%20report.docx?web=1"
SHARING = "https://example.sharepoint.com/:w:/s/Finance/opaque?e=token"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/file",
        "http://example.sharepoint.com/file",
        "https://example.sharepoint.com.evil.test/file",
        "https://example.sharepoint.us/file",
        "https://user@example.sharepoint.com/file",
        "https://example.sharepoint.com:444/file",
        "https://example.sharepoint.com\\@evil.test/file",
        " https://example.sharepoint.com/file",
        "https://example.sharepoint.com/file\n",
        "https://example.sharepoint.com:bad/file",
        BASE + "/../Other/file",
        BASE + "/%2e%2e/Other/file",
        BASE + "/a%2Fb",
        BASE + "/a%5Cb",
        BASE + "/a%00b",
        BASE + "/%ff",
    ],
)
async def test_invalid_links_stop_before_http(url):
    async with graph(lambda _: pytest.fail("Unexpected provider request")) as client:
        with pytest.raises(IntegrationValidationError) as error:
            await resolve_link(client, url=url, drives={"drive": BASE})
    assert error.value.error_code == "link_not_supported"


@pytest.mark.parametrize(
    "suffix",
    [
        "/Forms/AllItems.aspx?id=%2Fsites%2FFinance%2FDocuments%2FReports",
        "/Forms/AllItems.aspx?id=%2Fsites%2FFinance%2FDocuments%2Freport.docx",
        "/Forms/AllItems.aspx?RootFolder=%2Fsites%2FFinance%2FDocuments%2FReports",
        "/Forms/AllItems.aspx",
        "/Forms/AllItems.aspx?viewid=example",
        "/Forms/CustomView.aspx?id=%2Fsites%2FFinance%2FDocuments%2FReports",
        "/%46orms/ALLITEMS.aspx?id=%2Fsites%2FFinance%2FDocuments%2FReports",
    ],
)
async def test_browser_views_reject_with_direct_link_guidance_before_credentials(
    monkeypatch, suffix
):
    credentials = AsyncMock()
    monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", credentials)
    selected = replace(entry(), permissions_metadata={"web_url": BASE})
    url = BASE + suffix
    with pytest.raises(IntegrationValidationError) as error:
        await sharepoint_open_link(context(selected), url)
    assert error.value.error_code == "link_not_supported"
    assert "direct" in error.value.user_message
    credentials.assert_not_awaited()
    async with graph(lambda _: pytest.fail("A browser view must not issue a request")) as client:
        with pytest.raises(IntegrationValidationError) as error:
            await resolve_link(client, url=url, drives={"drive": BASE})
    assert error.value.error_code == "link_not_supported"


@pytest.mark.parametrize("same_connection", [False, True])
@pytest.mark.parametrize("invalid_first", [False, True])
@pytest.mark.parametrize(
    "cached_url",
    ["https://unsupported.example.com/library", BASE + "/%ff", BASE + "/a%2Fb"],
)
async def test_invalid_cached_urls_do_not_block_healthy_direct_links(
    monkeypatch, same_connection, invalid_first, cached_url
):
    selected = replace(entry(), permissions_metadata={"web_url": BASE})
    invalid = replace(entry("invalid"), permissions_metadata={"web_url": cached_url})
    if same_connection:
        invalid = replace(invalid, connection_id=selected.connection_id)
    entries = (invalid, selected) if invalid_first else (selected, invalid)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1.0/drives/drive/root:/Quarterly report.docx"
        return httpx2.Response(200, json=file_metadata())

    ctx = context(*entries)
    ctx.tool_name = DEFINITION.name
    async with graph(handler) as client:
        credentials = AsyncMock(return_value=client)
        monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", credentials)
        output = await sharepoint_open_link(ctx, DIRECT)
    typed = SharePointLinkOutput.model_validate(output)
    assert len(requests) == credentials.await_count == audit.await_count == 1
    assert credentials.call_args.args[1] == selected
    assert len(typed.results) == 1
    assert typed.results[0].status == "success"
    assert typed.results[0].external_id == "drive"
    assert audit.call_args.kwargs["external_ref"] == "drive:file"


@pytest.mark.parametrize(
    "cached_url", ["", "https://unsupported.example.com/library", BASE + "/%ff"]
)
async def test_unusable_cached_urls_remain_selected_for_sharing(cached_url):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path.startswith("/v1.0/shares/u!")
        return httpx2.Response(200, json=file_metadata())

    async with graph(handler) as client:
        data = await resolve_link(client, url=SHARING, drives={"drive": cached_url})
    assert len(requests) == 1
    assert data["reference"].drive_id == "drive"


@pytest.mark.parametrize(
    "url", ["https://unsupported.example.com/file", BASE + "/%ff", BASE + "/%2e%2e/file"]
)
async def test_malformed_supplied_urls_stop_before_credentials(monkeypatch, url):
    credentials = AsyncMock()
    monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", credentials)
    selected = replace(entry(), permissions_metadata={"web_url": BASE})
    with pytest.raises(IntegrationValidationError) as error:
        await sharepoint_open_link(context(selected), url)
    assert error.value.error_code == "link_not_supported"
    credentials.assert_not_awaited()


@pytest.mark.parametrize(
    "base,suffix,expected",
    [
        (BASE, "/Quarterly%20report.docx?web=1", "/Quarterly%20report.docx"),
        (BASE, "/report.aspx?web=1", "/report.aspx"),
        (BASE, "/AllItems.aspx?web=1", "/AllItems.aspx"),
        (BASE, "/Forms/notes.txt?web=1", "/Forms/notes.txt"),
        (BASE, "/%E6%96%87%20%23%25.docx", "/%E6%96%87%20%23%25.docx"),
        (BASE, "", ""),
        ("https://example-my.sharepoint.com/personal/reader/Documents", "/notes.txt", "/notes.txt"),
    ],
)
async def test_direct_links_use_selected_drive_paths_and_bounded_projection(base, suffix, expected):
    requests = []

    def handler(request):
        requests.append(request)
        path = "/v1.0/drives/drive/root" + (":" + expected if expected else "")
        assert request.url.raw_path.split(b"?")[0] == path.encode()
        assert dict(request.url.params) == {"$select": ITEM_SELECT + ",sharepointIds"}
        assert "prefer" not in request.headers
        return httpx2.Response(200, json=fixture("path_item.json"))

    async with graph(handler) as client:
        data = await resolve_link(client, url=base + suffix, drives={"drive": base})
    assert len(requests) == 1
    assert data["reference"].drive_id == "drive"
    assert data["name"].source_kind == "sharepoint_drive_item"
    assert DOWNLOAD_URL not in str(data)
    assert "downloadUrl" not in str(data)


@pytest.mark.parametrize(
    "url",
    [
        SHARING,
        BASE + "-other/file.docx",
        "https://other.sharepoint.com/sites/Finance/Documents/file.docx",
    ],
)
async def test_sharing_encoding_and_prefix_boundaries(url):
    def handler(request):
        path = request.url.path
        assert path.startswith("/v1.0/shares/u!") and path.endswith("/driveItem")
        token = path.split("/")[3][2:]
        assert urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode() == url
        assert "prefer" not in request.headers
        return httpx2.Response(200, json=file_metadata())

    async with graph(handler) as client:
        assert (await resolve_link(client, url=url, drives={"drive": BASE}))[
            "reference"
        ].item_id == "file"


async def test_unselected_item_names_site_and_library_without_returning_content():
    item = fixture("share_item.json")
    async with graph(lambda _: httpx2.Response(200, json=item)) as client:
        with pytest.raises(IntegrationValidationError) as error:
            await resolve_link(client, url=SHARING, drives={"drive": BASE})
    assert error.value.error_code == "library_not_selected"
    message = error.value.user_message
    assert error.value.library.content == "Finance / Documents"
    assert "Refresh discovery" in message and "Active Context" in message
    assert error.value.library.source_kind == "sharepoint_drive_item"
    assert DOWNLOAD_URL not in message and len(message) <= 1000


@pytest.mark.parametrize(
    "status,url,code",
    [
        (404, DIRECT, "not_found"),
        (403, DIRECT, "access_denied"),
        (403, SHARING, "link_not_supported"),
        (404, SHARING, "not_found"),
    ],
)
async def test_provider_failures_have_safe_recovery_codes(status, url, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(status, json={"error": {"message": "PRIVATE_PROVIDER_BODY"}})

    async with graph(handler) as client:
        with pytest.raises(IntegrationValidationError) as error:
            await resolve_link(client, url=url, drives={"drive": BASE})
    assert error.value.error_code == code
    assert "PRIVATE_PROVIDER_BODY" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"remoteItem": {}},
        {"package": {}},
        {"parentReference": {}},
        {"id": "bad id"},
        {"parentReference": {"driveId": "other"}},
    ],
)
async def test_invalid_or_foreign_direct_metadata_never_returns_a_reference(changes):
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(**changes))) as client:
        with pytest.raises(IntegrationValidationError):
            await resolve_link(
                client, url=DIRECT, drives={"drive": BASE, "other": BASE + "/nested"}
            )


@pytest.mark.parametrize("drives", [(), ("drive", "drive")])
async def test_empty_or_ambiguous_context_stops_before_credentials(monkeypatch, drives):
    client = AsyncMock()
    monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", client)
    with pytest.raises(ModelRetry):
        await sharepoint_open_link(context(*(entry(drive) for drive in drives)), DIRECT)
    client.assert_not_awaited()


@pytest.mark.parametrize("url", [DIRECT, SHARING])
async def test_one_request_per_connection_with_actual_result_library_and_audit(monkeypatch, url):
    first = entry("first")
    selected = replace(
        entry(), connection_id=first.connection_id, permissions_metadata={"web_url": BASE}
    )
    other = entry("other")
    ignored = replace(entry(), provider_key="outlook_mail", resource_type="outlook_mailbox")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=file_metadata())

    ctx = context(first, selected, other, ignored)
    ctx.tool_name = DEFINITION.name
    async with graph(handler) as client:
        credentials = AsyncMock(return_value=client)
        monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", credentials)
        output = await sharepoint_open_link(ctx, url)
    typed = SharePointLinkOutput.model_validate(output)
    expected_count = 1 if url == DIRECT else 2
    assert len(requests) == credentials.await_count == audit.await_count == expected_count
    assert len(typed.results) == expected_count
    assert typed.results[0].external_id == "drive"
    assert typed.results[0].data.reference.drive_id == "drive"
    assert audit.call_args_list[0].kwargs["external_ref"] == "drive:file"
    if url == SHARING:
        assert typed.results[1].error_code == "library_not_selected"
        assert audit.call_args_list[1].kwargs["status"] == "failure"
    public = typed.model_dump_json()
    assert (
        str(selected.connection_id) not in public
        and str(selected.integration_resource_id) not in public
    )
    assert DOWNLOAD_URL not in public


@pytest.mark.parametrize("nested_first", [False, True])
@pytest.mark.parametrize("same_connection", [False, True])
async def test_longest_library_prefix_selects_only_its_connection(
    monkeypatch, nested_first, same_connection
):
    outer = replace(entry("outer"), permissions_metadata={"web_url": BASE})
    nested = replace(entry(), permissions_metadata={"web_url": BASE + "/nested"})
    if same_connection:
        nested = replace(nested, connection_id=outer.connection_id)
    ctx = context(*((nested, outer) if nested_first else (outer, nested)))
    ctx.tool_name = DEFINITION.name
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/v1.0/drives/drive/root:/notes.txt"
        return httpx2.Response(200, json=file_metadata())

    async with graph(handler) as client:
        credentials = AsyncMock(return_value=client)
        monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", credentials)
        output = await sharepoint_open_link(ctx, BASE + "/nested/notes.txt?web=1")
    [result] = SharePointLinkOutput.model_validate(output).results
    assert result.status == "success" and result.external_id == "drive"
    assert len(requests) == credentials.await_count == audit.await_count == 1
    assert credentials.call_args.args[1] == nested
    assert audit.call_args.kwargs["external_id"] == "drive"


@pytest.mark.parametrize("cancel_at", ["credentials", "provider"])
async def test_link_cancellation_propagates_without_attempting_later_connections(
    monkeypatch, cancel_at
):
    first = entry()
    ctx = context(first, entry("later"))
    ctx.tool_name = DEFINITION.name
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    requests = []

    def handler(request):
        requests.append(request)
        raise asyncio.CancelledError

    async with graph(handler) as client:
        credentials = AsyncMock(return_value=client)
        if cancel_at == "credentials":
            credentials.side_effect = asyncio.CancelledError
        monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", credentials)
        with pytest.raises(asyncio.CancelledError):
            await sharepoint_open_link(ctx, SHARING)
    assert credentials.await_count == audit.await_count == 1
    assert credentials.call_args.args[1] == first
    assert len(requests) == (1 if cancel_at == "provider" else 0)
    assert audit.call_args.kwargs["status"] == "failure"
    assert audit.call_args.kwargs["error_code"] == "CancelledError"


async def test_failed_connections_keep_only_their_own_recovery_hint(monkeypatch):
    ctx = context(entry("first"), entry("second"), entry("third"))
    ctx.tool_name = DEFINITION.name
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 3:
            return httpx2.Response(404, json={"error": {"message": "PRIVATE_PROVIDER_BODY"}})
        site = "Finance" if len(requests) == 1 else "Research"
        return httpx2.Response(
            200,
            json=file_metadata(
                parentReference={"driveId": "outside"},
                sharepointIds={"siteUrl": f"https://example.sharepoint.com/sites/{site}"},
                webUrl=f"https://example.sharepoint.com/sites/{site}/Documents/notes.txt",
            ),
        )

    async with graph(handler) as client:
        credentials = AsyncMock(return_value=client)
        monkeypatch.setattr("integrations.sharepoint.tools.open_link.drive_client", credentials)
        output = await sharepoint_open_link(ctx, SHARING)
    first, second, third = SharePointLinkOutput.model_validate(output).results
    assert first.data.library.content == "Finance / Documents"
    assert second.data.library.content == "Research / Documents"
    assert third.data is None
    assert [item.error_code for item in (first, second, third)] == [
        "library_not_selected",
        "library_not_selected",
        "not_found",
    ]
    assert len(requests) == credentials.await_count == audit.await_count == 3
    assert [call.kwargs["external_id"] for call in audit.call_args_list] == [
        "first",
        "second",
        "third",
    ]
    assert all(call.kwargs["status"] == "failure" for call in audit.call_args_list)


def test_link_registration_and_code_mode_schema():
    validate_definition(DEFINITION)
    assert DEFINITION.code_eligible and DEFINITION.default_policy == "auto"
    assert DEFINITION.egress == "provider_query" and DEFINITION.timeout == 90
    assert not DEFINITION.integration_binding.requires_write
    stub = render_tool_stub(DEFINITION)
    assert "def sharepoint_open_link(" in stub and "SharePointLinkOutput" in stub
    schema = DEFINITION.to_pydantic_tool().function_schema.json_schema
    assert set(schema["properties"]) == {"url"}
    assert schema["properties"]["url"]["maxLength"] == 8192
