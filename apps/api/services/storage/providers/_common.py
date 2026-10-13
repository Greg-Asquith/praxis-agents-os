# apps/api/services/storage/providers/_common.py

"""Shared helpers for concrete storage provider adapters."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import IO, Any
from uuid import UUID

from services.storage.domain import StorageBucket, StorageObjectRef
from services.storage.errors import StorageProviderUnavailableError, StorageValidationError
from services.storage.platform_buckets import validate_platform_ref
from services.storage.workspace_buckets import workspace_id_for_ref

_PROVIDER_LABELS = {
    "azure_blob": "Azure Blob",
    "gcs": "GCS",
    "s3": "S3",
}


def require_setting(value: str | None, name: str, *, provider_key: str) -> str:
    stripped = (value or "").strip()
    if stripped:
        return stripped
    provider_label = _PROVIDER_LABELS.get(provider_key, provider_key)
    raise StorageProviderUnavailableError(
        f"{name} is required for {provider_label} storage",
        provider_key=provider_key,
        operation="configure_provider",
    )


def require_content_type(
    content_type: str,
    *,
    provider_key: str,
    ref: StorageObjectRef,
) -> str:
    normalized = content_type.strip()
    if normalized:
        return normalized
    raise StorageValidationError(
        "Signed upload content_type is required",
        provider_key=provider_key,
        operation="create_signed_upload",
        bucket=ref.bucket.value,
        object_key=ref.key,
    )


def require_staged_import(
    source: StorageObjectRef, destination: StorageObjectRef, *, provider_key: str
) -> UUID:
    """Returns the destination workspace when the refs are a staging-to-workspace import."""
    validate_platform_ref(source)
    workspace_id = (
        workspace_id_for_ref(destination) if destination.bucket == StorageBucket.PRIVATE else None
    )
    if workspace_id is None:
        raise StorageValidationError(
            "Staged imports must land in a workspace bucket",
            provider_key=provider_key,
            operation="import_staged_object",
            bucket=destination.bucket.value,
            object_key=destination.key,
        )
    return workspace_id


async def spool_chunks(chunks: AsyncIterator[bytes]) -> IO[bytes]:
    """Writes chunks to an anonymous temporary file and rewinds it; the caller closes it."""
    spooled = await asyncio.to_thread(tempfile.TemporaryFile)
    try:
        async for chunk in chunks:
            await asyncio.to_thread(spooled.write, chunk)
        await asyncio.to_thread(spooled.seek, 0)
    except BaseException:
        spooled.close()
        raise
    return spooled


def string_metadata(metadata: Any) -> dict[str, str]:
    return {str(key): str(value) for key, value in (metadata or {}).items()}


def as_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
