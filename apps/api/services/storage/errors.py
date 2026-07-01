# apps/api/services/storage/errors.py

"""Structured storage service errors."""

from typing import Any

from core.exceptions.integration import IntegrationError


class StorageError(IntegrationError):
    """Base error for application-managed object storage."""

    _title_override = "Storage Error"

    def __init__(
        self,
        message: str,
        *,
        provider_key: str | None = None,
        operation: str | None = None,
        bucket: str | None = None,
        object_key: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        self.bucket = bucket
        self.object_key = object_key
        super().__init__(
            message,
            provider_key=provider_key,
            operation=operation,
            original_error=original_error,
        )

    def to_problem_details(self) -> dict[str, Any]:
        problem = super().to_problem_details()
        if self.bucket:
            problem["bucket"] = self.bucket
        if self.object_key:
            problem["object_key"] = self.object_key
        return problem


class StorageValidationError(StorageError):
    """Raised when a storage ref, content type, or object payload is invalid."""

    _status_override = 400
    _title_override = "Storage Validation Error"


class StorageSignatureError(StorageError):
    """Raised when a signed storage capability is invalid or expired."""

    _status_override = 403
    _title_override = "Storage Signature Error"


class StorageNotFoundError(StorageError):
    """Raised when an object does not exist."""

    _status_override = 404
    _title_override = "Storage Object Not Found"


class StorageProviderUnavailableError(StorageError):
    """Raised when the configured provider has no usable adapter yet."""

    _status_override = 501
    _title_override = "Storage Provider Unavailable"
