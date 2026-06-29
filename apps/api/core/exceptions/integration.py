# apps/api/core/exceptions/integration.py

"""
Custom exceptions that follow our app's error handling patterns for integration operations.

These exceptions provide structured error information for integration operations and integrate with our RFC 7807 problem details format.
"""

from typing import Any

# Integration Services Errors


class IntegrationError(Exception):
    """
    Base exception for integration service errors.

    Provides context about which provider and operation failed for better
    observability and debugging.
    """

    # Subclasses may set these to override the default 500 response values.
    _status_override: int | None = None
    _title_override: str | None = None
    _type_override: str | None = None

    def __init__(
        self,
        message: str,
        *,
        provider_key: str | None = None,
        connection_id: str | None = None,
        operation: str | None = None,
        original_error: Exception | None = None,
    ):
        """
        Initialize integration error with context.

        Args:
            message: Human-readable error message
            provider_key: Provider identifier (e.g., 'google_drive')
            connection_id: Connection UUID
            operation: Operation being performed (e.g., 'list_files', 'upload_file')
            original_error: Original exception that caused this error
        """
        self.provider_key = provider_key
        self.connection_id = connection_id
        self.operation = operation
        self.original_error = original_error

        # Build detailed message
        parts = [message]
        if provider_key:
            parts.append(f"provider={provider_key}")
        if connection_id:
            parts.append(f"connection={connection_id}")
        if operation:
            parts.append(f"operation={operation}")

        detailed_message = " | ".join(parts)
        super().__init__(detailed_message)

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        status = self._status_override if self._status_override is not None else 500
        title = self._title_override if self._title_override is not None else "Integration Error"
        type_ = (
            self._type_override
            if self._type_override is not None
            else f"https://httpstatuses.com/{status}"
        )
        problem: dict[str, Any] = {
            "type": type_,
            "title": title,
            "status": status,
            "detail": str(self),
        }

        if self.provider_key:
            problem["provider_key"] = self.provider_key

        if self.connection_id:
            problem["connection_id"] = str(self.connection_id)

        if self.operation:
            problem["operation"] = self.operation

        return problem


class IntegrationConnectionError(IntegrationError):
    """Raised when connection is invalid or not active."""

    _status_override = 400
    _title_override = "Integration Connection Error"


class IntegrationAuthError(IntegrationError):
    """Raised when authentication or token refresh fails."""

    _status_override = 401
    _title_override = "Integration Authentication Error"


class IntegrationRateLimitError(IntegrationError):
    """Raised when rate limit is exceeded."""

    _status_override = 429
    _title_override = "Integration Rate Limit Error"


class IntegrationTimeoutError(IntegrationError):
    """Raised when an integration operation times out."""

    _status_override = 504
    _title_override = "Integration Timeout Error"


class IntegrationNotFoundError(IntegrationError):
    """Raised when resource is not found."""

    _status_override = 404
    _title_override = "Integration Resource Not Found"


class IntegrationValidationError(IntegrationError):
    """Raised when input validation fails."""

    _status_override = 400
    _title_override = "Integration Validation Error"


class IntegrationPermissionError(IntegrationError):
    """Raised when the integration denies access (403)."""

    _status_override = 403
    _title_override = "Integration Permission Error"
