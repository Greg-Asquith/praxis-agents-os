"""Original-byte copies, workspace file effects, and scoped audit evidence."""

import base64
import hashlib
import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from core.settings import settings
from integrations.sharepoint.operations.copy_item import copy_item
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.settings import sharepoint_settings
from integrations.sharepoint.tools.copy_to_files import DEFINITION, sharepoint_copy_to_files
from integrations.sharepoint.tools.schemas import SharePointCopyOutput
from services.agents.runtime.tools.contract import validate_definition
from services.agents.runtime.untrusted import frame_untrusted_content
from tests.integrations.sharepoint.support import (
    DOCX_CONTENT_TYPE,
    DOWNLOAD_URL,
    context,
    entry,
    file_metadata,
    graph,
)
from utils.quickxorhash import quickxorhash

FIXTURES = Path(__file__).with_name("fixtures")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6a1sAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def public_downloads(monkeypatch):
    monkeypatch.setattr(
        "services.integrations.microsoft_graph.client._resolve_host",
        AsyncMock(return_value=("8.8.8.8",)),
    )
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 1)


@asynccontextmanager
async def transaction():
    yield


@pytest.mark.parametrize(
    "filename,content_type",
    [("document.docx", DOCX_CONTENT_TYPE), ("sheet.xlsx", XLSX), ("pixel.png", "image/png")],
)
@pytest.mark.parametrize("folder", [None, "  Research  "])
async def test_copy_retains_original_bytes_and_records_file_effects(
    monkeypatch, caplog, filename, content_type, folder
):
    content = PNG if filename.endswith(".png") else (FIXTURES / filename).read_bytes()
    ctx = context(entry())
    ctx.tool_name = "sharepoint_copy_to_files"
    ctx.deps.db = SimpleNamespace(begin_nested=transaction)
    ctx.deps.user = SimpleNamespace(id=uuid4())
    ctx.deps.conversation = SimpleNamespace(id=uuid4())
    saved_file = SimpleNamespace(id=uuid4(), name=filename)
    saved_revision = SimpleNamespace(id=uuid4())
    saved_folder = SimpleNamespace(id=uuid4())
    create = AsyncMock(
        return_value=SimpleNamespace(
            file=saved_file, revision=saved_revision, bytes_written=len(content)
        )
    )
    resolve = AsyncMock(return_value=saved_folder)
    reserve = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr("services.integrations.files.create_copy.reserve_file_revision", reserve)
    link = AsyncMock()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr("services.integrations.files.create_copy.create_file_with_revision", create)
    monkeypatch.setattr("services.integrations.files.create_copy.resolve_folder_by_name", resolve)
    monkeypatch.setattr(
        "services.integrations.files.create_copy.create_conversation_file_references", link
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    caplog.set_level(logging.DEBUG)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "graph.microsoft.com":
            assert "$select" not in request.url.params
            return httpx2.Response(
                200,
                json=file_metadata(
                    name=filename, size=len(content), file={"mimeType": content_type}
                ),
            )
        assert "Authorization" not in request.headers
        return httpx2.Response(200, content=content)

    async with graph(handler) as client:
        monkeypatch.setattr(
            "integrations.sharepoint.tools.copy_to_files.drive_client",
            AsyncMock(return_value=client),
        )
        result = await sharepoint_copy_to_files(
            ctx, SharePointDriveItemReference(drive_id="drive", item_id="file"), folder
        )
    data = SharePointCopyOutput.model_validate(result).results[0].data
    assert data is not None
    assert data.version == '"version-1"'
    assert data.file_id == data.reference.entity_id == saved_file.id
    assert data.revision_id == saved_revision.id
    assert data.name.content == filename and data.content_type.content == content_type
    assert data.size_bytes == len(content)
    assert data.source.reference.item_id == "file"
    assert len(requests) == 2
    reserve.assert_awaited_once()
    assert reserve.await_args.kwargs["content"] == content
    assert create.await_args.kwargs["reservation"] is reserve.return_value
    assert create.await_args.kwargs["content"] == content
    assert create.await_args.kwargs["workspace"] is ctx.deps.workspace
    assert create.await_args.kwargs["actor"].agent_id == ctx.deps.agent.id
    assert create.await_args.kwargs["resolved_folder"] is (saved_folder if folder else None)
    if folder:
        assert resolve.await_args.kwargs["name"] == "Research"
        assert resolve.await_args.kwargs["workspace"] is ctx.deps.workspace
    else:
        resolve.assert_not_awaited()
    link.assert_awaited_once_with(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        conversation_id=ctx.deps.conversation.id,
        file_ids=[saved_file.id],
        created_by_user_id=ctx.deps.user.id,
    )
    audit.assert_awaited_once()
    evidence = audit.await_args.kwargs
    assert evidence["status"] == "success" and evidence["external_ref"] == "drive:file"
    effect = evidence["operation_detail"].outcome_groups[0].outcomes[0].effects[0]
    assert effect.fields == {
        "source": "drive:file",
        "version": '"version-1"',
        "file_id": str(saved_file.id),
        "revision_id": str(saved_revision.id),
    }
    assert (
        "PRAXIS_UNTRUSTED_CONTENT" in frame_untrusted_content(result)["results"][0]["data"]["name"]
    )
    visible = str(result) + str(evidence) + caplog.text
    assert DOWNLOAD_URL not in visible and "PRIVATE_DOWNLOAD_SECRET" not in visible
    assert "@microsoft.graph.downloadUrl" not in visible
    assert content.hex() not in visible


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"file": {"mimeType": "application/octet-stream"}}, "unsupported_type"),
        ({"file": {}}, "unsupported_type"),
        ({"file": {"mimeType": 12}}, "unsupported_type"),
        ({"folder": {}}, "unsupported_type"),
        ({"package": {}}, "unsupported_type"),
        ({"size": 6}, "too_large"),
        ({"size": -1}, None),
        ({"eTag": None}, None),
        ({"parentReference": {"driveId": "other"}}, None),
        ({"remoteItem": {}}, None),
    ],
)
async def test_invalid_metadata_stops_before_download(monkeypatch, changes, code):
    monkeypatch.setattr(sharepoint_settings, "SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES", 5)
    async with graph(lambda _: httpx2.Response(200, json=file_metadata(**changes))) as client:
        download = AsyncMock()
        monkeypatch.setattr(client, "get_bytes", download)
        with pytest.raises(IntegrationValidationError) as caught:
            await copy_item(client, drive_id="drive", item_id="file")
        assert caught.value.error_code == code
        download.assert_not_awaited()


class CopyStream(httpx2.AsyncByteStream):
    closed = False

    async def __aiter__(self):
        yield b"123"
        yield b"456"

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("limited_by", ["download", "category"])
@pytest.mark.parametrize("metadata_size", [1, 6])
async def test_metadata_and_stream_respect_smaller_category_or_download_limit(
    monkeypatch, limited_by, metadata_size, caplog
):
    monkeypatch.setattr(
        sharepoint_settings,
        "SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES",
        5 if limited_by == "download" else 100,
    )
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_IMAGE", 5 if limited_by == "category" else 100)
    stream = CopyStream()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "graph.microsoft.com":
            return httpx2.Response(
                200,
                json=file_metadata(
                    name="pixel.png", size=metadata_size, file={"mimeType": "image/png"}
                ),
            )
        return httpx2.Response(200, stream=stream)

    async with graph(handler) as client:
        with pytest.raises(IntegrationValidationError) as caught:
            await copy_item(client, drive_id="drive", item_id="file")
    assert caught.value.error_code == "too_large"
    assert len(requests) == (1 if metadata_size == 6 else 2)
    assert stream.closed is (metadata_size == 1)
    assert (
        "PRIVATE_DOWNLOAD_SECRET"
        not in "".join(traceback.format_exception(caught.value)) + caplog.text
    )


@pytest.mark.parametrize("drives", [(), ("other",), ("drive", "drive")])
async def test_unselected_or_ambiguous_library_stops_before_credentials(monkeypatch, drives):
    client = AsyncMock()
    monkeypatch.setattr("integrations.sharepoint.tools.copy_to_files.drive_client", client)
    ctx = context(*(entry(drive) for drive in drives))
    with pytest.raises(ModelRetry):
        await sharepoint_copy_to_files(
            ctx, SharePointDriveItemReference(drive_id="drive", item_id="file")
        )
    client.assert_not_awaited()


def test_copy_definition_uses_native_internal_write_policy_and_read_binding():
    validate_definition(DEFINITION)
    assert DEFINITION.effect == "write" and DEFINITION.effect_scope == "internal"
    assert DEFINITION.egress == "provider_query" and DEFINITION.default_policy == "auto"
    assert DEFINITION.supports_auto and DEFINITION.supports_approval
    assert DEFINITION.code_eligible and DEFINITION.timeout == 300
    assert not DEFINITION.integration_binding.requires_write


@pytest.mark.parametrize(
    "hashes",
    [
        None,
        {},
        {"quickXorHash": None, "sha1Hash": None},
        {"quickXorHash": quickxorhash(b"text")},
        {"sha1Hash": hashlib.sha1(b"text", usedforsecurity=False).hexdigest()},
        {"sha1Hash": hashlib.sha1(b"text", usedforsecurity=False).hexdigest().upper()},
        {
            "quickXorHash": quickxorhash(b"text"),
            "sha1Hash": hashlib.sha1(b"text", usedforsecurity=False).hexdigest(),
        },
    ],
)
@pytest.mark.parametrize("transport", [False, True])
async def test_copy_checks_available_hashes_and_accepts_missing_hashes(hashes, transport):
    facet = {"mimeType": "text/plain"}
    if hashes is not None:
        facet["hashes"] = hashes
    metadata = file_metadata(size=4, file=facet)
    if transport:

        def handler(request):
            if request.url.host == "graph.microsoft.com":
                return httpx2.Response(200, json=metadata)
            return httpx2.Response(200, content=b"text")

        async with graph(handler) as client:
            item, data = await copy_item(client, drive_id="drive", item_id="file")
    else:
        client = AsyncMock()
        client.get.return_value = metadata
        client.get_bytes.return_value = b"text"
        item, data = await copy_item(client, drive_id="drive", item_id="file")
    assert data == b"text"
    assert item["file"] == facet
    assert item["size"] == len(data)
    assert item["eTag"] == '"version-1"'
    assert "@microsoft.graph.downloadUrl" not in item


@pytest.mark.parametrize(
    "content,hashes",
    [
        (b"tex", None),
        (b"texts", None),
        (b"text", {"quickXorHash": quickxorhash(b"next")}),
        (b"text", {"sha1Hash": hashlib.sha1(b"next", usedforsecurity=False).hexdigest()}),
        (b"text", {"quickXorHash": "invalid"}),
        (b"text", {"sha1Hash": 12}),
        (b"text", []),
        (
            b"text",
            {
                "quickXorHash": quickxorhash(b"text"),
                "sha1Hash": hashlib.sha1(b"next", usedforsecurity=False).hexdigest(),
            },
        ),
    ],
)
@pytest.mark.parametrize("transport", [False, True])
async def test_inconsistent_copy_fails_before_local_side_effects(
    monkeypatch, caplog, content, hashes, transport
):
    metadata = file_metadata(size=4, file={"mimeType": "text/plain", "hashes": hashes})
    ctx = context(entry())
    ctx.tool_name = "sharepoint_copy_to_files"
    ctx.deps.db = SimpleNamespace(begin_nested=transaction)
    effects = {}
    for name in (
        "reserve_file_revision",
        "create_file_with_revision",
        "resolve_folder_by_name",
        "create_conversation_file_references",
    ):
        effects[name] = AsyncMock()
        monkeypatch.setattr(f"services.integrations.files.create_copy.{name}", effects[name])
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    if transport:

        def handler(request):
            if request.url.host == "graph.microsoft.com":
                return httpx2.Response(200, json=metadata)
            return httpx2.Response(200, content=content)

        async with graph(handler) as client:
            monkeypatch.setattr(
                "integrations.sharepoint.tools.copy_to_files.drive_client",
                AsyncMock(return_value=client),
            )
            result = await sharepoint_copy_to_files(
                ctx, SharePointDriveItemReference(drive_id="drive", item_id="file"), "Research"
            )
        failure = result["results"][0]
        assert failure["status"] == "error"
        assert failure["error_code"] == "source_changed"
        assert not any(call.kwargs["status"] == "success" for call in audit.await_args_list)
        evidence = str(result) + str(audit.await_args_list) + caplog.text
    else:
        client = AsyncMock()
        client.get.return_value = metadata
        client.get_bytes.return_value = content
        with pytest.raises(IntegrationValidationError) as caught:
            await copy_item(client, drive_id="drive", item_id="file")
        assert caught.value.error_code == "source_changed"
        assert caught.value.operation == "copy_to_files"
        evidence = "".join(traceback.format_exception(caught.value)) + caplog.text
    for effect in effects.values():
        effect.assert_not_awaited()
    assert DOWNLOAD_URL not in evidence and "PRIVATE_DOWNLOAD_SECRET" not in evidence
