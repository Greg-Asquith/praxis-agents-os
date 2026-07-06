"""Tests for the workspace file contract."""

from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.files.contract import (
    FILE_CONTRACT,
    FileCategory,
    contract_for_content_type,
    is_editable,
    is_ingestible,
    max_size_bytes,
    require_matching_pair,
)
from services.files.utils import file_prefix, revision_markdown_key, revision_object_key
from services.storage.paths import validate_object_key


def test_contract_entries_round_trip_by_content_type() -> None:
    for entry in FILE_CONTRACT:
        assert contract_for_content_type(entry.content_type) == entry


def test_require_matching_pair_rejects_mismatch_and_unknown_type() -> None:
    with pytest.raises(AppValidationError):
        require_matching_pair("application/pdf", ".docx")

    with pytest.raises(AppValidationError):
        require_matching_pair("application/octet-stream", ".bin")


def test_extensions_are_unique_across_catalog() -> None:
    extension_to_content_type: dict[str, str] = {}
    for entry in FILE_CONTRACT:
        for extension in entry.extensions:
            assert extension not in extension_to_content_type
            extension_to_content_type[extension] = entry.content_type


def test_max_size_bytes_resolves_settings_keys() -> None:
    pdf = contract_for_content_type("application/pdf")
    mp4 = contract_for_content_type("video/mp4")

    assert max_size_bytes(pdf) == settings.MAX_FILE_SIZE_DOCUMENT
    assert max_size_bytes(mp4) == settings.MAX_FILE_SIZE_VIDEO


def test_ingestible_is_true_only_for_document_types() -> None:
    ingestible_types = {
        entry.content_type
        for entry in FILE_CONTRACT
        if entry.category == FileCategory.INGESTIBLE_DOCUMENT
    }

    for entry in FILE_CONTRACT:
        assert is_ingestible(entry.content_type) is (entry.content_type in ingestible_types)


def test_editable_is_true_only_for_text_types() -> None:
    editable_types = {
        entry.content_type
        for entry in FILE_CONTRACT
        if entry.category == FileCategory.EDITABLE_TEXT
    }

    for entry in FILE_CONTRACT:
        assert is_editable(entry.content_type) is (entry.content_type in editable_types)


def test_file_storage_keys_use_expected_shapes() -> None:
    workspace_id = uuid4()
    file_id = uuid4()
    revision_id = uuid4()

    object_key = revision_object_key(workspace_id, file_id, revision_id, ".pdf")
    markdown_key = revision_markdown_key(workspace_id, file_id, revision_id)
    prefix = file_prefix(workspace_id, file_id)

    assert object_key == f"workspaces/{workspace_id}/files/{file_id}/{revision_id}.pdf"
    assert markdown_key == f"workspaces/{workspace_id}/files/{file_id}/{revision_id}.extracted.md"
    assert prefix == f"workspaces/{workspace_id}/files/{file_id}"
    assert validate_object_key(object_key) == object_key
    assert validate_object_key(markdown_key) == markdown_key
    assert validate_object_key(prefix) == prefix
