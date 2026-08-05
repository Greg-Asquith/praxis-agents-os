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
    request_content_type: str,
    request_content_length: int | None,
    chunks: AsyncIterator[bytes],
) -> None:
    """Validate and persist an exactly sized signed upload."""
    provider = get_storage_provider()
    ref = make_storage_object_ref(bucket, object_key)
    provider.require_valid_upload_signature(
        ref=ref,
        expires=expires,
        signature=signature,
        content_type=content_type,
        expected_size_bytes=expected_size_bytes,
    )

    if request_content_type.strip().lower() != content_type.strip().lower():
        raise StorageValidationError(
            "Signed upload Content-Type does not match the request",
            provider_key=provider.provider_key,
            operation="accept_signed_upload",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )

    if request_content_length is not None and request_content_length != expected_size_bytes:
        raise StorageValidationError(
            "Signed upload Content-Length does not match the granted size",
            provider_key=provider.provider_key,
            operation="accept_signed_upload",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )

    data = bytearray()
    async for chunk in chunks:
        data.extend(chunk)
        if len(data) > expected_size_bytes:
            raise StorageValidationError(
                "Signed upload exceeds the granted size",
                provider_key=provider.provider_key,
                operation="accept_signed_upload",
                bucket=ref.bucket.value,
                object_key=ref.key,
            )
    if len(data) != expected_size_bytes:
        raise StorageValidationError(
            "Signed upload size does not match the granted size",
            provider_key=provider.provider_key,
            operation="accept_signed_upload",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )

    await provider.put_object(ref, bytes(data), content_type=content_type, overwrite=False)
