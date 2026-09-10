# apps/api/services/storage/utils.py

"""Shared helpers for storage service operations."""

import asyncio
import hashlib
import logging
from collections.abc import Coroutine
from typing import Any

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


async def read_copy_content(
    provider: StorageProvider,
    ref: StorageObjectRef,
    expected_size: int,
    expected_sha256: str,
) -> bytes:
    """Read a pinned object with an enforced total byte limit."""
    stored = await provider.stat_object(ref)
    if stored is None:
        raise storage_object_not_found(provider, ref, operation="copy_object")
    if stored.size_bytes != expected_size:
        raise StoragePreconditionError("Copy source size changed", operation="copy_object")
    content = bytearray()
    digest = hashlib.sha256()
    async for chunk in provider.stream_object(ref):
        if len(content) + len(chunk) > expected_size:
            raise StoragePreconditionError(
                "Copy exceeds its declared size", operation="copy_object"
            )
        content.extend(chunk)
        digest.update(chunk)
    if len(content) != expected_size or digest.hexdigest() != expected_sha256:
        raise StoragePreconditionError("Copy content changed", operation="copy_object")
    return bytes(content)


async def validate_copy_destination(
    provider: StorageProvider,
    ref: StorageObjectRef,
    expected_size: int,
    expected_sha256: str,
    content_type: str,
) -> StoredObject | None:
    """Adopt a retry destination only when its bytes and safe metadata agree."""
    stored = await provider.stat_object(ref)
    if stored is None:
        return None
    if (
        stored.content_type != content_type
        or stored.cache_control != "private, no-store"
        or stored.metadata
    ):
        raise StoragePreconditionError("Copy destination already exists", operation="copy_object")
    await read_copy_content(provider, ref, expected_size, expected_sha256)
    return stored


async def await_copy_mutation[T](mutation: Coroutine[Any, Any, T]) -> T:
    """Drain provider writes before cleanup, including repeated cancellation."""
    task = asyncio.create_task(mutation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result
