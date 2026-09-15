"""Required file citations and optional listing metadata."""

import logging
import traceback
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.sharepoint.operations.convert_item import convert_item
from integrations.sharepoint.operations.download_item import download_item
from integrations.sharepoint.operations.list_children import list_children
from integrations.sharepoint.operations.search_items import search_items
from integrations.sharepoint.operations.utils import MAX_CITATION_URL_CHARS
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.read_file import sharepoint_read_file
from integrations.sharepoint.tools.schemas import SharePointFileOutput
from tests.integrations.sharepoint.support import context, entry, file_metadata, graph


@pytest.mark.parametrize(
    "citation",
    [
        None,
        123,
        {},
        "",
        " ",
        "notes.txt",
        "//example.com/notes.txt",
        "javascript:PRIVATE_CITATION_SECRET",
        "ftp://example.com/notes.txt",
        "https:///notes.txt",
        "https://",
        "https://example.com:invalid/notes.txt",
        "https://[invalid/notes.txt",
        "https://example.com/notes\n.txt",
        "https://example.com/notes\x00.txt",
        "https://example.com/notes file.txt",
        "https://example.com\\notes.txt",
        "https://PRIVATE_CITATION_SECRET@example.com/notes.txt",
        "https://example.com/" + "a" * MAX_CITATION_URL_CHARS,
    ],
)
async def test_unusable_citation_fails_before_download(monkeypatch, citation, caplog):
    caplog.set_level(logging.DEBUG)
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(webUrl=citation))) as client:
        download = AsyncMock(return_value=b"notes")
        monkeypatch.setattr(client, "get_bytes", download)
        with pytest.raises(IntegrationValidationError) as caught:
            await download_item(client, drive_id="drive", item_id="file")
        download.assert_not_awaited()
    assert caught.value.operation == "read_file"
    assert caught.value.original_error is None
    evidence = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert "PRIVATE_CITATION_SECRET" not in evidence
    assert "PRIVATE_DOWNLOAD_SECRET" not in evidence


async def test_absent_citation_fails_before_download(monkeypatch):
    item = file_metadata()
    del item["webUrl"]
    async with graph(lambda _: httpx2.Response(200, json=item)) as client:
        download = AsyncMock(return_value=b"notes")
        monkeypatch.setattr(client, "get_bytes", download)
        with pytest.raises(IntegrationValidationError):
            await download_item(client, drive_id="drive", item_id="file")
        download.assert_not_awaited()


@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_long_citation_survives_read_with_provenance(monkeypatch, scheme):
    prefix = f"{scheme}://example.com/notes%20file.txt?value="
    citation = prefix + "a" * (MAX_CITATION_URL_CHARS - len(prefix))
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(webUrl=citation))) as client:
        monkeypatch.setattr(client, "get_bytes", AsyncMock(return_value=b"notes"))
        result = await convert_item(client, drive_id="drive", item_id="file")
    assert result["web_url"].content == citation
    assert result["web_url"].source_kind == "sharepoint_drive_item"
    assert result["web_url"].source_ref == "drive:file"
    assert result["markdown"].content == "notes"
    assert "PRIVATE_DOWNLOAD_SECRET" not in str(result)


@pytest.mark.parametrize("citation", [None, 123, "", "notes.txt"])
async def test_listing_and_search_keep_optional_citations(citation):
    item = file_metadata(webUrl=citation)
    async with graph(lambda _: httpx2.Response(200, json={"value": [item]})) as client:
        results = [
            await list_children(client, drive_id="drive"),
            await search_items(client, drive_id="drive", query="notes"),
        ]
    for result in results:
        assert result["count"] == 1
        assert result["items"][0]["web_url"].content == (
            citation if isinstance(citation, str) else ""
        )


async def test_rejected_citation_is_absent_from_public_failure_and_audit(monkeypatch, caplog):
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    citation = "https://PRIVATE_CITATION_SECRET@example.com/notes.txt"
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(webUrl=citation))) as client:
        download = AsyncMock(return_value=b"notes")
        monkeypatch.setattr(client, "get_bytes", download)
        monkeypatch.setattr(
            "integrations.sharepoint.tools.read_file.drive_client", AsyncMock(return_value=client)
        )
        ctx = context(entry())
        ctx.tool_name = "sharepoint_read_file"
        result = await sharepoint_read_file(
            ctx, SharePointDriveItemReference(drive_id="drive", item_id="file")
        )
        download.assert_not_awaited()
    typed = SharePointFileOutput.model_validate(result)
    assert typed.results[0].status == "error"
    assert audit.await_count == 1
    assert audit.call_args.kwargs["external_ref"] is None
    evidence = typed.model_dump_json() + str(audit.call_args) + caplog.text
    assert "PRIVATE_CITATION_SECRET" not in evidence
    assert "PRIVATE_DOWNLOAD_SECRET" not in evidence
