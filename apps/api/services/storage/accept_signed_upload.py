# apps/api/services/storage/accept_signed_upload.py

"""Accept a signed upload through the active storage provider."""

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
    request_content_type: str,
    data: bytes,
) -> None:
    """Persist a signed upload for the configured provider."""
    provider = get_storage_provider()
    ref = make_storage_object_ref(bucket, object_key)
    provider.require_valid_upload_signature(
        ref=ref,
        expires=expires,
        signature=signature,
        content_type=content_type,
    )

    if request_content_type.strip().lower() != content_type.strip().lower():
        raise StorageValidationError(
            "Signed upload Content-Type does not match the request",
            provider_key=provider.provider_key,
            operation="accept_signed_upload",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )

    await provider.put_object(ref, data, content_type=content_type)
