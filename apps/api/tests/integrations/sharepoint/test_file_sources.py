"""Workspace source revision checks before approved SharePoint uploads."""

import importlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.sharepoint.operations.file_source import load_file_source, resolve_file_source
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools.update_file import DEFINITION as UPDATE, sharepoint_update_file
from integrations.sharepoint.tools.write_file import DEFINITION as WRITE, sharepoint_write_file
from services.agents.runtime.entity_references.domain import FileReference
from services.files.utils import file_revision_ref, sha256_hex
from services.storage.errors import StorageNotFoundError
from tests.factories import build_file, build_file_revision, build_workspace
from tests.integrations.sharepoint.support import context, entry, file_metadata
from utils.quickxorhash import quickxorhash

DATA = b"original workspace document bytes"
REMOTE = SharePointDriveItemReference(drive_id="drive", item_id="file", kind="file")


def set_stream(storage, chunks):
    storage.yielded = []

    async def stream(ref):
        for chunk in chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            storage.yielded.append(chunk)
            yield chunk

    storage.stream_object.side_effect = stream


@pytest.fixture
async def source_file(db_session, monkeypatch):
    workspace = build_workspace(slug=f"source-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    file = build_file(workspace=workspace, size_bytes=len(DATA), content_hash=sha256_hex(DATA))
    db_session.add(file)
    await db_session.flush()
    revision = build_file_revision(file)
    db_session.add(revision)
    await db_session.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db_session.flush()
    storage = SimpleNamespace(
        provider_key="local_fs",
        get_object=AsyncMock(),
        stat_object=AsyncMock(return_value=SimpleNamespace(size_bytes=len(DATA))),
        stream_object=Mock(),
    )
    set_stream(storage, [DATA])
    monkeypatch.setattr(
        importlib.import_module("services.integrations.files.read_file_source"),
        "get_storage_provider",
        lambda: storage,
    )
    reference = FileReference(entity_id=file.id, label="Untrusted model label")
    source = await resolve_file_source(db_session, workspace=workspace, reference=reference)
    return SimpleNamespace(
        workspace=workspace,
        file=file,
        revision=revision,
        reference=reference,
        pin=source.approval_details(),
        storage=storage,
    )


async def test_current_pinned_revision_reads_immutable_private_object(db_session, source_file):
    source = await load_file_source(
        db_session,
        workspace=source_file.workspace,
        reference=source_file.reference,
        pinned=source_file.pin,
    )
    assert source.data == DATA
    assert source.approval_details()["name"] == "example.pdf"
    source_file.storage.stat_object.assert_awaited_once_with(
        file_revision_ref(source_file.revision)
    )
    source_file.storage.stream_object.assert_called_once_with(
        file_revision_ref(source_file.revision)
    )
    source_file.storage.get_object.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        "revision",
        "file_id",
    ],
)
async def test_changed_or_missing_pin_is_rejected(db_session, source_file, change):
    pin = dict(source_file.pin)
    if change == "revision":
        revision = build_file_revision(source_file.file, revision_number=2, revision_kind="edit")
        db_session.add(revision)
        await db_session.flush()
        source_file.file.current_revision_id = revision.id
        await db_session.flush()
    elif change == "missing":
        pin = None
    elif change == "bytes":
        set_stream(source_file.storage, [b"different stored bytes"])
    else:
        pin[change] = "changed"
    with pytest.raises(IntegrationValidationError) as caught:
        await load_file_source(
            db_session, workspace=source_file.workspace, reference=source_file.reference, pinned=pin
        )
    assert caught.value.error_code == "source_changed"
    if change != "bytes":
        source_file.storage.stat_object.assert_not_awaited()
        source_file.storage.stream_object.assert_not_called()


async def test_source_in_another_workspace_is_unavailable(db_session, source_file):
    other = build_workspace(slug=f"other-{uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    with pytest.raises(IntegrationValidationError) as caught:
        await load_file_source(
            db_session, workspace=other, reference=source_file.reference, pinned=source_file.pin
        )
    assert caught.value.error_code == "source_unavailable"
    source_file.storage.stat_object.assert_not_awaited()
    source_file.storage.stream_object.assert_not_called()


@pytest.mark.parametrize("action", ["write", "update"])
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "source_changed",
        "type_mismatch",
    ],
)
async def test_source_uploads_use_reviewed_bytes_and_fail_before_writes(
    db_session, source_file, monkeypatch, action, failure
):
    definition = WRITE if action == "write" else UPDATE
    ctx = context(replace(entry(), write_allowed=True))
    ctx.tool_name = definition.name
    ctx.deps.db = db_session
    ctx.deps.workspace = source_file.workspace
    args = (
        {"name": "report.pdf"}
        if action == "write"
        else {"file": REMOTE, "expected_version": '"version-1"'}
    ) | {"source": source_file.reference}
    display = await definition.approval_display_args(ctx.deps, args)
    assert display["_source"] == source_file.pin
    assert display["_source"]["name"] != source_file.reference.label
    monkeypatch.setattr(
        "integrations.sharepoint.tools.write_utils.approved_display_args", lambda _: display
    )
    metadata = file_metadata(
        name="report.pdf", size=len(DATA), file={"mimeType": "application/pdf"}
    )
    provider = SimpleNamespace(
        get=AsyncMock(return_value=metadata),
        post=AsyncMock(return_value={"uploadUrl": "https://example.sharepoint.com/private-upload"}),
        upload_fragment=AsyncMock(
            return_value={
                **metadata,
                "eTag": '"version-2"',
                "file": {
                    "mimeType": "application/pdf",
                    "hashes": {"quickXorHash": quickxorhash(DATA)},
                },
            }
        ),
    )
    factory = AsyncMock(return_value=provider)
    monkeypatch.setattr("integrations.sharepoint.tools.write_utils.drive_client", factory)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    if failure == "source_changed":
        display["_source"]["revision_id"] = str(uuid4())
    storage = source_file.storage
    if failure == "oversized_stat":
        storage.stat_object.return_value.size_bytes = len(DATA) + 1
    elif failure == "oversized_stream":
        set_stream(storage, [DATA, b"overflow", b"must not be read"])
    elif failure == "short":
        set_stream(storage, [DATA[:-1]])
    elif failure == "hash":
        set_stream(storage, [b"x" * len(DATA)])
    elif failure == "missing_stat":
        storage.stat_object.return_value = None
    elif failure == "missing_stream":
        set_stream(storage, [StorageNotFoundError("PRIVATE_STORAGE_KEY")])
    if failure == "type_mismatch":
        if action == "update":
            metadata["file"]["mimeType"] = "image/png"
        else:
            args["name"] = "report.png"
    result = await (sharepoint_write_file if action == "write" else sharepoint_update_file)(
        ctx, **args
    )
    if failure:
        assert result["results"][0]["status"] == "error"
        expected = (
            "source_unavailable"
            if failure in {"missing_stat", "missing_stream"}
            else "type_mismatch"
            if failure == "type_mismatch"
            else "source_changed"
        )
        assert result["results"][0]["error_code"] == expected
        provider.post.assert_not_awaited()
        if failure != "type_mismatch":
            factory.assert_not_awaited()
        if failure in {"oversized_stat", "missing_stat"}:
            storage.stream_object.assert_not_called()
        if failure == "oversized_stream":
            assert storage.yielded == [DATA, b"overflow"]
        assert "PRIVATE_STORAGE_KEY" not in str(result) + str(audit.await_args_list)
    else:
        assert result["results"][0]["data"]["outcome"] == "applied"
        assert provider.upload_fragment.await_args.args[1] == DATA
        assert [str(call.kwargs["status"]) for call in audit.await_args_list] == [
            "pending",
            "success",
        ]
