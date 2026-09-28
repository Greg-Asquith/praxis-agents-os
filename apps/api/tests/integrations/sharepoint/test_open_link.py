"""Link resolution, library boundaries, and connection-level request limits."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.sharepoint.operations.resolve_link import resolve_link
from integrations.sharepoint.operations.utils import ITEM_SELECT
from integrations.sharepoint.tools.open_link import DEFINITION, sharepoint_open_link
from integrations.sharepoint.tools.schemas import SharePointLinkOutput
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


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/file",
        "http://example.sharepoint.com/file",
        "https://example.sharepoint.com.evil.test/file",
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


@pytest.mark.parametrize(
    "base,suffix,expected",
    [
        (BASE, "/Quarterly%20report.docx?web=1", "/Quarterly%20report.docx"),
        (BASE, "/report.aspx?web=1", "/report.aspx"),
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
    "changes",
    [
        {"remoteItem": {}},
        {"package": {}},
    ],
)
async def test_invalid_or_foreign_direct_metadata_never_returns_a_reference(changes):
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(**changes))) as client:
        with pytest.raises(IntegrationValidationError):
            await resolve_link(
                client, url=DIRECT, drives={"drive": BASE, "other": BASE + "/nested"}
            )


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
