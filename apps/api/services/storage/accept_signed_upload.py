# apps/api/services/storage/accept_signed_upload.py

"""Accept a signed upload through the active storage provider."""

from collections.abc import AsyncIterator

from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import StorageValidationError
from services.storage.factory import get_storage_provider


async def accept_signed_upload(
    bucket: StorageBucket,
    object_key: str,
    *,
    expires: int,
    signature: str,
    content_type: str,
    expected_size_bytes: int,
    bounded: bool = False,
    request_content_type: str,
    request_content_length: int | None,
    chunks: AsyncIterator[bytes],
) -> None:
    """Validate and persist a signed upload of the granted size, or up to it when bounded."""
    provider = get_storage_provider()
    ref = make_storage_object_ref(bucket, object_key)
    provider.require_valid_upload_signature(
        ref=ref,
        expires=expires,
        signature=signature,
        content_type=content_type,
        expected_size_bytes=expected_size_bytes,
        bounded=bounded,
    )

    if request_content_type.strip().lower() != content_type.strip().lower():
        raise StorageValidationError(
            "Signed upload Content-Type does not match the request",
            provider_key=provider.provider_key,
            operation="accept_signed_upload",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )

    if request_content_length is not None and (
        request_content_length > expected_size_bytes
        or (not bounded and request_content_length != expected_size_bytes)
    ):
        raise StorageValidationError(
            "Signed upload Content-Length does not match the granted size",
            provider_key=provider.provider_key,
            operation="accept_signed_upload",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )

    async def bounded_chunks() -> AsyncIterator[bytes]:
        received = 0
        async for chunk in chunks:
            received += len(chunk)
            if received > expected_size_bytes:
                raise StorageValidationError(
                    "Signed upload exceeds the granted size",
                    provider_key=provider.provider_key,
                    operation="accept_signed_upload",
                    bucket=ref.bucket.value,
                    object_key=ref.key,
                )
            yield chunk
        if not bounded and received != expected_size_bytes:
            raise StorageValidationError(
                "Signed upload size does not match the granted size",
                provider_key=provider.provider_key,
                operation="accept_signed_upload",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )

    # A failed check stops the stream, and the provider removes what it wrote.
    await provider.put_object_stream(ref, bounded_chunks(), content_type=content_type)
