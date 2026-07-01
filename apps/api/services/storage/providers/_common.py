"""Shared helpers for concrete storage provider adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.storage.domain import StorageObjectRef
from services.storage.errors import StorageProviderUnavailableError, StorageValidationError

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


def string_metadata(metadata: Any) -> dict[str, str]:
    return {str(key): str(value) for key, value in (metadata or {}).items()}


def as_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
