# apps/api/services/assets/utils.py

"""Shared helpers for asset upload validation and cleanup."""

import logging

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.storage.domain import StorageBucket, StorageObjectRef, StoredObject
from services.storage.factory import get_storage_provider
from services.storage.paths import unique_object_key
from services.storage.provider import StorageProvider

logger = logging.getLogger(__name__)

RASTER_ICON_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def parse_content_types(value: str) -> set[str]:
    """Parse a comma-separated content-type setting."""
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def normalize_content_type(content_type: str) -> str:
    """Return a canonical content type, rejecting header parameters."""
    normalized = content_type.strip().lower()
    if not normalized or ";" in normalized:
        raise AppValidationError("Unsupported file type", field="content_type")
    return normalized


def allowed_avatar_content_types() -> set[str]:
    """Return content types allowed for user-uploaded avatars."""
    return parse_content_types(settings.ALLOWED_IMAGE_TYPES)


def allowed_workspace_icon_content_types() -> set[str]:
    """Return raster content types allowed for workspace icons."""
    return parse_content_types(settings.ALLOWED_ICON_TYPES) & set(RASTER_ICON_CONTENT_TYPES)


def validate_upload_metadata(
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
    allowed_content_types: set[str],
    max_size_bytes: int,
    asset_label: str,
) -> str:
    """Validate client-declared file metadata before issuing a signed upload."""
    normalized_content_type = normalize_content_type(content_type)
    if normalized_content_type not in allowed_content_types:
        raise AppValidationError(f"Unsupported {asset_label} file type", field="content_type")
    if size_bytes > max_size_bytes:
        raise AppValidationError(f"{asset_label.capitalize()} file is too large", field="size_bytes")
    if extension_for_content_type(normalized_content_type) is None:
        raise AppValidationError(f"Unsupported {asset_label} file type", field="content_type")
    if not filename.strip():
        raise AppValidationError("Filename is required", field="filename")
    return normalized_content_type


def extension_for_content_type(content_type: str) -> str | None:
    """Return a safe extension for a supported image content type."""
    return _IMAGE_EXTENSIONS.get(content_type)


def public_asset_ref(prefix: str, *, content_type: str) -> StorageObjectRef:
    """Create a unique public storage ref under a validated asset prefix."""
    extension = extension_for_content_type(content_type)
    if extension is None:
        raise AppValidationError("Unsupported file type", field="content_type")
    return StorageObjectRef(
        bucket=StorageBucket.PUBLIC,
        key=unique_object_key(prefix, f"asset{extension}"),
    )


def public_ref_from_key(object_key: str) -> StorageObjectRef:
    """Return a public storage ref for a stored object key."""
    return StorageObjectRef(bucket=StorageBucket.PUBLIC, key=object_key)


def validate_stored_object(
    stored: StoredObject | None,
    *,
    expected_content_type: str,
    allowed_content_types: set[str],
    max_size_bytes: int,
    asset_label: str,
) -> StoredObject:
    """Validate provider metadata after the browser has uploaded bytes."""
    if stored is None:
        raise AppValidationError(f"Uploaded {asset_label} was not found", field="upload_token")

    stored_content_type = normalize_content_type(stored.content_type or "")
    if stored_content_type != expected_content_type or stored_content_type not in allowed_content_types:
        raise AppValidationError(f"Uploaded {asset_label} has an invalid file type", field="content_type")
    if stored.size_bytes > max_size_bytes:
        raise AppValidationError(f"Uploaded {asset_label} is too large", field="size_bytes")
    return stored


def resolve_public_url(
    stored: StoredObject,
    *,
    provider: StorageProvider,
    asset_label: str,
) -> str:
    """Resolve the provider-owned public URL for a confirmed public asset."""
    public_url = stored.public_url or provider.public_url(stored.ref)
    if not public_url:
        raise AppValidationError(
            f"Uploaded {asset_label} is not available as a public asset",
            field="upload_token",
        )
    return public_url


async def best_effort_delete_public_object(
    object_key: str,
    *,
    provider: StorageProvider | None = None,
) -> None:
    """Delete an old or rejected public object without failing the user operation."""
    try:
        storage_provider = provider or get_storage_provider()
        await storage_provider.delete_object(public_ref_from_key(object_key))
    except Exception:
        logger.warning(
            "Failed to delete public asset object",
            extra={"object_key": object_key},
            exc_info=True,
        )
