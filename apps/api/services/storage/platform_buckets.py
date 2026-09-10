# apps/api/services/storage/platform_buckets.py

"""Platform-private storage namespace and bucket resolution."""

from services.storage.domain import StorageBucket, StorageObjectRef
from services.storage.errors import StorageValidationError


def validate_platform_ref(ref: StorageObjectRef) -> None:
    """Validates the namespace of a platform-private object."""
    if ref.bucket != StorageBucket.PLATFORM_PRIVATE or not ref.key.startswith("platform/"):
        raise StorageValidationError(
            "Platform-private storage keys must use the platform/ namespace",
            operation="resolve_platform_bucket",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )


def platform_bucket_name(
    ref: StorageObjectRef,
    configured_name: str | None,
    *,
    setting_name: str,
    provider_key: str,
    public_bucket_name: str,
    workspace_bucket_prefix: str,
) -> str:
    """Resolves an explicit platform bucket without a public fallback."""
    from services.storage.providers._common import require_setting

    validate_platform_ref(ref)
    name = require_setting(configured_name, setting_name, provider_key=provider_key)
    if name == public_bucket_name.strip():
        raise StorageValidationError(
            f"{setting_name} must differ from the public bucket or container",
            provider_key=provider_key,
            operation="resolve_platform_bucket",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )
    if name.startswith(f"{workspace_bucket_prefix}-"):
        raise StorageValidationError(
            f"{setting_name} must not use the workspace bucket prefix",
            provider_key=provider_key,
            operation="resolve_platform_bucket",
            bucket=ref.bucket.value,
            object_key=ref.key,
        )
    return name
