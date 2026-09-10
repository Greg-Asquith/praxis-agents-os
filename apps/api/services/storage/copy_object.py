# apps/api/services/storage/copy_object.py

"""Copy authorised, pinned content into independent private storage."""

from collections.abc import Awaitable, Callable

from services.storage.domain import StorageBucket, StorageObjectRef, StoredObject
from services.storage.errors import StoragePreconditionError, StorageValidationError
from services.storage.provider import StorageProvider
from services.storage.utils import (
    await_copy_mutation,
    copy_staging_ref,
    read_copy_content,
    validate_copy_destination,
)
from services.storage.workspace_buckets import workspace_id_for_ref

MAX_COPY_BYTES = 262_144_000


async def copy_object(
    provider: StorageProvider,
    source: StorageObjectRef,
    destination: StorageObjectRef,
    *,
    authorise: Callable[[StorageObjectRef, StorageObjectRef], Awaitable[None]],
    expected_size_bytes: int,
    expected_sha256: str,
    content_type: str,
) -> StoredObject:
    """Copy a pinned revision, recovering an identical destination on retry.

    The domain caller must serialise copies to this destination with resource
    locks, validate source visibility and destination write authority in ``authorise``, and commit its audit and rows
    only after success. Reuse the destination identity when retrying a failed
    database commit. No HTTP or agent tool exposes this storage operation.
    """
    if (
        {source.bucket, destination.bucket}
        != {StorageBucket.PRIVATE, StorageBucket.PLATFORM_PRIVATE}
        or not 0 <= expected_size_bytes <= MAX_COPY_BYTES
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or not content_type.strip()
    ):
        raise StorageValidationError("Invalid private storage copy", operation="copy_object")
    workspace_id_for_ref(source)
    stage = copy_staging_ref(destination)
    await authorise(source, destination)
    try:
        existing = await validate_copy_destination(
            provider, destination, expected_size_bytes, expected_sha256, content_type
        )
        if existing is not None:
            return existing
        content = await read_copy_content(provider, source, expected_size_bytes, expected_sha256)
        staged = await validate_copy_destination(
            provider, stage, expected_size_bytes, expected_sha256, content_type
        )
        if staged is None:
            staged = await await_copy_mutation(
                provider.put_object(
                    stage,
                    content,
                    content_type=content_type,
                    cache_control="private, no-store",
                    overwrite=False,
                )
            )
        del content
        await authorise(source, destination)
        try:
            await await_copy_mutation(
                provider.promote_object(stage, destination, expected_source_etag=staged.etag)
            )
        except Exception:
            # A provider can create the complete object before losing its response.
            recovered = await validate_copy_destination(
                provider, destination, expected_size_bytes, expected_sha256, content_type
            )
            if recovered is None:
                raise
            return recovered
        copied = await validate_copy_destination(
            provider, destination, expected_size_bytes, expected_sha256, content_type
        )
        if copied is None:
            raise StoragePreconditionError("Copy destination is missing", operation="copy_object")
        return copied
    finally:
        await await_copy_mutation(provider.delete_object(stage))
