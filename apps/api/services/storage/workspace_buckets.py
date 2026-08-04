# apps/api/services/storage/workspace_buckets.py

"""Workspace-private storage bucket naming and reference resolution."""

from __future__ import annotations

from uuid import UUID

from services.storage.domain import StorageBucket, StorageObjectRef
from services.storage.errors import StorageValidationError


def workspace_id_for_ref(ref: StorageObjectRef) -> UUID | None:
    """Resolve the workspace owning a private ref; public refs have no workspace bucket."""
    if ref.bucket == StorageBucket.PUBLIC:
        return None

    prefix, separator, _remainder = ref.key.partition("/")
    workspace_value, workspace_separator, _rest = _remainder.partition("/")
    if prefix != "workspaces" or separator != "/" or workspace_separator != "/":
        raise StorageValidationError(
            "Private storage keys must use the workspaces/{workspace_id}/ namespace",
            operation="resolve_workspace_bucket",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )
    try:
        return UUID(workspace_value)
    except ValueError as exc:
        raise StorageValidationError(
            "Private storage keys must contain a valid workspace ID",
            operation="resolve_workspace_bucket",
            bucket=ref.bucket.value,
            object_key=ref.key,
            original_error=exc,
        ) from exc


def workspace_bucket_name(prefix: str, workspace_id: UUID) -> str:
    """Return the provider bucket/container name for a workspace."""
    return f"{prefix}-{workspace_id}"


def s3_workspace_bucket_name(
    prefix: str,
    workspace_id: UUID,
    *,
    account_id: str,
    region: str,
) -> str:
    """Return an account-regional S3 bucket name for a workspace."""
    compact_workspace_id = _base36(workspace_id.int)
    name = f"{prefix}-{compact_workspace_id}-{account_id}-{region}-an"
    if len(name) > 63:
        raise StorageValidationError(
            "WORKSPACE_BUCKET_PREFIX is too long for the AWS account and region suffix",
            provider_key="s3",
            operation="resolve_workspace_bucket",
            bucket=name,
        )
    return name


def _base36(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, remainder = divmod(value, len(alphabet))
        encoded = alphabet[remainder] + encoded
    return encoded or "0"
