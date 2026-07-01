# apps/api/services/storage/utils.py

"""Shared helpers for storage service operations."""

from fastapi.responses import FileResponse, Response

from services.storage.domain import StorageObjectRef, StoredObject
from services.storage.errors import StorageNotFoundError
from services.storage.provider import StorageProvider
from services.storage.providers.local import LocalStorageProvider


async def storage_object_response(
    provider: StorageProvider,
    ref: StorageObjectRef,
    stored: StoredObject,
    *,
    headers: dict[str, str] | None = None,
) -> Response:
    """Render an object response using the active provider's best local path."""
    if isinstance(provider, LocalStorageProvider):
        return FileResponse(
            provider.filesystem_path(ref),
            media_type=stored.content_type,
            headers=headers,
        )

    return Response(
        content=await provider.get_object(ref),
        media_type=stored.content_type,
        headers=headers,
    )


def storage_object_headers(stored: StoredObject) -> dict[str, str]:
    """Build response headers from provider object metadata."""
    headers = {}
    if stored.cache_control:
        headers["Cache-Control"] = stored.cache_control
    if stored.etag:
        headers["ETag"] = stored.etag
    return headers


def storage_object_not_found(
    provider: StorageProvider,
    ref: StorageObjectRef,
    *,
    operation: str,
) -> StorageNotFoundError:
    """Build a provider-aware storage not-found error."""
    return StorageNotFoundError(
        "Storage object not found",
        provider_key=provider.provider_key,
        operation=operation,
        bucket=ref.bucket.value,
        object_key=ref.key,
    )
