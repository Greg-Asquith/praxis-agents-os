"""Tests for shared attachment text conversion and provenance framing."""

import importlib
from unittest.mock import AsyncMock

import pytest

from models.files import File, FileRevision
from services.files import markdown_for_revision
from services.storage.domain import StorageObjectRef
from tests.factories import build_file, build_file_revision, build_workspace


class RecordingStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.read_keys: list[str] = []

    async def get_object(self, ref: StorageObjectRef) -> bytes:
        self.read_keys.append(ref.key)
        return self.objects[ref.key]


async def test_markdown_for_revision_reads_stored_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment_text_module = importlib.import_module("services.files.attachment_text")
    file, revision = _build_document()
    revision.markdown_object_key = f"{revision.object_key}.extracted.md"
    storage = RecordingStorage(
        {
            revision.object_key: b"original bytes",
            revision.markdown_object_key: "# Stored résumé".encode(),
        }
    )
    convert = AsyncMock(side_effect=AssertionError("stored Markdown must not be converted"))
    monkeypatch.setattr(attachment_text_module, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(attachment_text_module, "convert_document_to_markdown", convert)

    markdown = await markdown_for_revision(file, revision, max_bytes=2_000_000)

    assert markdown == "# Stored résumé"
    assert storage.read_keys == [revision.markdown_object_key]
    convert.assert_not_awaited()


async def test_markdown_for_revision_converts_original_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment_text_module = importlib.import_module("services.files.attachment_text")
    file, revision = _build_document()
    storage = RecordingStorage({revision.object_key: b"original bytes"})
    convert = AsyncMock(return_value="# Converted")
    monkeypatch.setattr(attachment_text_module, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(attachment_text_module, "convert_document_to_markdown", convert)

    markdown = await markdown_for_revision(file, revision, max_bytes=123_456)

    assert markdown == "# Converted"
    assert storage.read_keys == [revision.object_key]
    convert.assert_awaited_once_with(
        b"original bytes",
        content_type=revision.content_type,
        filename=file.name,
        max_bytes=123_456,
    )
    assert file.processing_status == "pending"
    assert revision.markdown_object_key is None


def _build_document(
    *,
    content_type: str = "application/vnd.openxmlformats-officedocument.presentationml.presentation",
) -> tuple[File, FileRevision]:
    workspace = build_workspace()
    file = build_file(
        workspace=workspace,
        name="Q3 board deck.pptx",
        content_type=content_type,
        extension=".pptx",
        size_bytes=14_208_113,
        processing_status="pending",
    )
    revision = build_file_revision(
        file,
        content_type=content_type,
        size_bytes=14_208_113,
    )
    file.current_revision_id = revision.id
    return file, revision
