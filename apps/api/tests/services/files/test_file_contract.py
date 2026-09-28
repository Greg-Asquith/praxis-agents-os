"""Tests for the workspace file contract."""

from uuid import uuid4

import pytest

from core.exceptions.general import AppValidationError
from services.files.contract import (
    require_matching_pair,
)
from services.files.utils import file_prefix, revision_markdown_key, revision_object_key
from services.storage.paths import validate_object_key


def test_require_matching_pair_rejects_mismatch_and_unknown_type() -> None:
    with pytest.raises(AppValidationError):
        require_matching_pair("application/pdf", ".docx")

    with pytest.raises(AppValidationError):
        require_matching_pair("application/octet-stream", ".bin")

    with pytest.raises(AppValidationError):
        require_matching_pair("application/msword", ".docx")


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
