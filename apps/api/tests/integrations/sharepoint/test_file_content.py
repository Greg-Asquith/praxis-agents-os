"""Selected-library file downloads, conversion, and confidential URL boundaries."""

import logging
import traceback
from functools import partial
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationError, IntegrationValidationError
from core.settings import settings
from integrations.sharepoint.operations.convert_item import convert_item
from integrations.sharepoint.operations.find_in_item import find_in_item
from integrations.sharepoint.operations.read_item_window import read_item_window
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.settings import sharepoint_settings
from integrations.sharepoint.tools.read_file import DEFINITION, sharepoint_read_file
from integrations.sharepoint.tools.schemas import SharePointFileOutput
from services.agents.runtime.untrusted import UntrustedNode
from tests.integrations.sharepoint.support import (
    DOCX_CONTENT_TYPE as DOCX,
    DOWNLOAD_URL,
    HOSTILE_DOCX as HOSTILE,
    context,
    entry,
    file_metadata as metadata,
    graph,
)

FIXTURES = Path(__file__).with_name("fixtures")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(params=["bulk", "window", "find"])
def file_reader(request):
    if request.param == "find":
        return partial(find_in_item, query="notes", limit=10), "find_in_file"
    return (read_item_window if request.param == "window" else convert_item), "read_file"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        "services.integrations.microsoft_graph.client._resolve_host",
        AsyncMock(return_value=("8.8.8.8",)),
    )
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 1)


@pytest.mark.parametrize(
    "filename,content_type,marker",
    [
        ("document.docx", DOCX, "Quarterly Results"),
        ("sheet.xlsx", XLSX, "Revenue"),
    ],
)
async def test_real_documents_retain_provenance_and_hide_download_url(
    filename, content_type, marker, caplog
):
    data = (HOSTILE if filename.startswith("hostile") else FIXTURES / filename).read_bytes()
    requests = []
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx2")

    def handler(request):
        requests.append(request)
        if request.url.host == "graph.microsoft.com":
            assert request.headers["Authorization"] == "Bearer token"
            assert request.url.path == "/v1.0/drives/drive/items/file"
            item = metadata(name=filename, size=len(data), file={"mimeType": content_type})
            item["@microsoft.graph.downloadUrlNoAuth"] = (
                "https://example.com/PRIVATE_DOWNLOAD_SECRET"
            )
            item["createdBy"] = {"user": {"displayName": "PRIVATE_CREATOR_METADATA"}}
            # SharePoint omits the download annotation when metadata fields use $select.
            if "$select" in request.url.params:
                item.pop("@microsoft.graph.downloadUrl")
            return httpx2.Response(200, json=item)
        assert request.url.host == "8.8.8.8"
        assert request.headers["Host"] == "example.sharepoint.com"
        assert request.extensions["sni_hostname"] == "example.sharepoint.com"
        assert "Authorization" not in request.headers
        return httpx2.Response(200, content=data)

    async with graph(handler) as client:
        result = await read_item_window(client, drive_id="drive", item_id="file")
    assert len(requests) == 2
    assert marker.casefold() in result["markdown"].content.casefold()
    assert result["source"] == ("text" if content_type == "text/plain" else "converted")
    assert result["size_bytes"] == len(data) and not result["truncated"]
    for field in ("name", "content_type", "modified_at", "web_url", "markdown"):
        assert isinstance(result[field], UntrustedNode)
        assert result[field].source_kind == "sharepoint_drive_item"
        assert result[field].source_ref == "drive:file"
    assert "PRIVATE_DOWNLOAD_SECRET" not in str(result) + caplog.text
    assert "PRIVATE_CREATOR_METADATA" not in str(result)
    assert DOWNLOAD_URL not in str([record.__dict__ for record in caplog.records])


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"file": {"mimeType": "image/png"}}, "unsupported_type"),
        ({"size": 101}, "too_large"),
        ({"folder": {}}, "unsupported_type"),
    ],
)
async def test_rejected_metadata_never_downloads(monkeypatch, changes, code, file_reader):
    read, operation = file_reader
    monkeypatch.setattr(sharepoint_settings, "SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES", 100)
    async with graph(lambda _: httpx2.Response(200, json=metadata(**changes))) as client:
        download = AsyncMock()
        monkeypatch.setattr(client, "get_bytes", download)
        with pytest.raises(IntegrationValidationError) as caught:
            await read(client, drive_id="drive", item_id="file")
        assert caught.value.error_code == code
        assert caught.value.operation == (
            "get_item" if {"parentReference", "remoteItem", "id"} & changes.keys() else operation
        )
        download.assert_not_awaited()


class OversizedStream(httpx2.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        yield b"123"
        yield b"456"

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize(
    "length",
    [
        None,
        "1",
    ],
)
async def test_streamed_size_enforced_despite_metadata(monkeypatch, length, file_reader):
    read, operation = file_reader
    monkeypatch.setattr(sharepoint_settings, "SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES", 5)
    stream = OversizedStream()

    def handler(request):
        if request.url.host == "graph.microsoft.com":
            return httpx2.Response(200, json=metadata())
        return httpx2.Response(
            200, stream=stream, headers={} if length is None else {"Content-Length": length}
        )

    async with graph(handler) as client:
        with pytest.raises(IntegrationValidationError) as caught:
            await read(client, drive_id="drive", item_id="file")
    assert caught.value.operation == operation
    assert caught.value.error_code == "too_large"
    assert stream.closed


@pytest.mark.parametrize(
    "content_type,name",
    [
        ("text/plain", "bad.txt"),
        ("text/html", "bad.html"),
    ],
)
async def test_undecodable_or_corrupt_files_fail_safely(content_type, name, caplog, file_reader):
    read, operation = file_reader

    def handler(request):
        if request.url.host == "graph.microsoft.com":
            return httpx2.Response(200, json=metadata(name=name, file={"mimeType": content_type}))
        return httpx2.Response(200, content=b"\xff\xfe\x00broken")

    async with graph(handler) as client:
        with pytest.raises(IntegrationValidationError) as caught:
            await read(client, drive_id="drive", item_id="file")
    assert caught.value.operation == operation
    assert caught.value.error_code == "conversion_failed"
    assert caught.value.user_message == (
        "This file could not be converted to text. It may be protected or damaged. "
        "Try an unprotected copy."
    )
    assert f"operation={operation}" in str(caught.value)
    assert (
        "PRIVATE_DOWNLOAD_SECRET"
        not in "".join(traceback.format_exception(caught.value)) + caplog.text
    )


@pytest.mark.parametrize(
    "status",
    [
        302,
        403,
        404,
    ],
)
async def test_download_errors_hide_url_and_refuse_redirects(status, caplog, file_reader):
    read, operation = file_reader
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx2")
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "graph.microsoft.com":
            return httpx2.Response(200, json=metadata())
        if status == "timeout":
            raise httpx2.ReadTimeout(DOWNLOAD_URL, request=request)
        return httpx2.Response(status, content=DOWNLOAD_URL, headers={"Location": DOWNLOAD_URL})

    async with graph(handler) as client:
        with pytest.raises(IntegrationError) as caught:
            await read(client, drive_id="drive", item_id="file")
    assert len(requests) == 2
    assert caught.value.operation == operation
    if status == 423:
        assert caught.value.error_code == "protected"
    assert caught.value.original_error is None
    evidence = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert "PRIVATE_DOWNLOAD_SECRET" not in evidence


@pytest.mark.parametrize(
    "drives",
    [
        (),
        ("other",),
    ],
)
async def test_read_rejects_unselected_or_ambiguous_drive_before_credentials(monkeypatch, drives):
    client = AsyncMock()
    monkeypatch.setattr("integrations.sharepoint.tools.read_file.drive_client", client)
    with pytest.raises(ModelRetry):
        await sharepoint_read_file(
            context(*(entry(drive) for drive in drives)),
            SharePointDriveItemReference(drive_id="drive", item_id="file"),
        )
    client.assert_not_awaited()


async def test_windows_reconstruct_large_document_with_fresh_audited_reads(monkeypatch, caplog):
    data = (FIXTURES / "long_notes.txt").read_bytes()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    requests = []
    caplog.set_level(logging.DEBUG)

    def handler(request):
        requests.append(request)
        return (
            httpx2.Response(200, json=metadata(size=len(data)))
            if request.url.host == "graph.microsoft.com"
            else httpx2.Response(200, content=data)
        )

    ctx = context(entry())
    ctx.tool_name = DEFINITION.name
    reference = SharePointDriveItemReference(drive_id="drive", item_id="file")
    windows = []
    offset = 0
    async with graph(handler) as client:
        monkeypatch.setattr(
            "integrations.sharepoint.tools.read_file.drive_client", AsyncMock(return_value=client)
        )
        while True:
            result = await sharepoint_read_file(ctx, reference, offset=offset)
            window = SharePointFileOutput.model_validate(result).results[0].data
            windows.append(window)
            assert window.offset == offset
            assert window.total_bytes == len(data)
            assert window.limit_reached is False
            assert len(window.markdown.content.encode()) <= 65536
            if not window.truncated:
                assert window.hint is None
                break
            offset = window.end_offset
            assert f"offset={offset}" in window.hint
            assert "sharepoint_find_in_file" in window.hint
    assert len(windows) == 4
    assert "".join(window.markdown.content for window in windows).encode() == data
    assert len(requests) == 2 * len(windows) == 2 * audit.await_count
    assert "PRIVATE_DOWNLOAD_SECRET" not in str(windows) + str(audit.call_args_list) + caplog.text
