# apps/api/services/storage/utils.py

"""Shared helpers for storage service operations."""

import asyncio
import logging

from fastapi.responses import FileResponse, Response

from services.storage.domain import StorageObjectRef, StoredObject
from services.storage.errors import StorageNotFoundError, StoragePreconditionError
from services.storage.provider import StorageProvider
from services.storage.providers.local import LocalStorageProvider

logger = logging.getLogger(__name__)


async def promote_object_or_get_existing(
    provider: StorageProvider,
    source: StorageObjectRef,
    destination: StorageObjectRef,
    *,
    source_object: StoredObject,
) -> tuple[StoredObject, bool]:
    """Promote a validated source, returning a prior destination for crash recovery."""
    try:
        promoted = await provider.promote_object(
            source,
            destination,
            expected_source_etag=source_object.etag,
        )
    except StoragePreconditionError:
        existing = await provider.stat_object(destination)
        if existing is None:
            raise
        return existing, False
    return promoted, True


async def put_new_object_with_cleanup(
    provider: StorageProvider,
    ref: StorageObjectRef,
    content: bytes,
    *,
    content_type: str,
) -> StoredObject:
    """Write a new unique object and remove partial data when the write is interrupted."""
    try:
        return await provider.put_object(ref, content, content_type=content_type)
    except BaseException:
        cleanup = asyncio.create_task(provider.delete_object(ref))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            try:
                await cleanup
            except BaseException:
                logger.warning(
                    "Failed to clean up a cancelled storage write",
                    extra={"bucket": ref.bucket.value, "object_key": ref.key},
                    exc_info=True,
                )
        except Exception:
            logger.warning(
                "Failed to clean up an interrupted storage write",
                extra={"bucket": ref.bucket.value, "object_key": ref.key},
                exc_info=True,
            )
        raise


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
