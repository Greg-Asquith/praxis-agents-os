"""Storage key helpers for workspace files."""

from uuid import UUID

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.paths import validate_object_key


def normalize_extension(extension: str) -> str:
    normalized = extension.strip().lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized


def revision_object_key(
    workspace_id: UUID,
    file_id: UUID,
    revision_id: UUID,
    extension: str,
) -> str:
    """Build the private object key for a file revision."""
    key = (
        f"workspaces/{workspace_id}/files/{file_id}/"
        f"{revision_id}{normalize_extension(extension)}"
    )
    make_storage_object_ref(StorageBucket.PRIVATE, key)
    return key


def revision_markdown_key(workspace_id: UUID, file_id: UUID, revision_id: UUID) -> str:
    """Build the private object key for extracted revision markdown."""
    key = f"workspaces/{workspace_id}/files/{file_id}/{revision_id}.extracted.md"
    make_storage_object_ref(StorageBucket.PRIVATE, key)
    return key


def file_prefix(workspace_id: UUID, file_id: UUID) -> str:
    """Build the object-key prefix for all blobs belonging to a file."""
    return validate_object_key(f"workspaces/{workspace_id}/files/{file_id}")
