# apps/api/core/exceptions/general.py

"""
Custom exceptions that follow our app's error handling patterns for general errors.

These exceptions provide structured error information for general operations and integrate with our RFC 7807 problem details format.
"""

from typing import Any

from core.exceptions._problem import PROBLEM_RESERVED_KEYS as _PROBLEM_RESERVED_KEYS

# General Errors


class AppValidationError(Exception):
    """Exception for input validation errors"""

    _title: str = "Validation Error"

    def __init__(
        self,
        message: str,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.field = field
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/400",
            "title": self._title,
            "status": 400,
            "detail": self.message,
        }

        if self.field:
            problem["field"] = self.field

        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem


class NotFoundError(Exception):
    """Exception for resource not found errors"""

    def __init__(
        self,
        message: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/404",
            "title": "Resource Not Found",
            "status": 404,
            "detail": self.message,
        }

        if self.resource_type:
            problem["resource_type"] = self.resource_type

        if self.resource_id:
            problem["resource_id"] = self.resource_id

        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem


class ConflictError(Exception):
    """Exception for resource conflicts"""

    def __init__(
        self,
        message: str,
        conflicting_resource: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.conflicting_resource = conflicting_resource
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/409",
            "title": "Resource Conflict",
            "status": 409,
            "detail": self.message,
        }

        if self.conflicting_resource:
            problem["conflicting_resource"] = self.conflicting_resource

        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem


class CustomValueError(AppValidationError):
    """Exception for value errors. Thin subclass of AppValidationError with 'Value Error' title."""

    _title = "Value Error"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message=message, field=None, details=details)


class RequestBodyTooLargeError(Exception):
    """Exception for request body too large errors"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/413",
            "title": "Request Body Too Large",
            "status": 413,
            "detail": self.message,
        }

        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem


class ProblemDetailsError(Exception):
    """Generic typed exception for route-owned HTTP error contracts."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        title: str | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.title = title
        self.details = details or {}
        self.headers = headers or {}

    def to_problem_details(self) -> dict[str, Any]:
        problem = {
            "type": f"https://httpstatuses.com/{self.status_code}",
            "title": self.title or "HTTP Error",
            "status": self.status_code,
            "detail": self.message,
        }
        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )
        return problem


class RateLimitError(Exception):
    """Exception for rate limiting"""

    def __init__(
        self,
        message: str,
        retry_after: int | None = None,
        limit: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        self.limit = limit
        self.status_code = 429
        self.details = details or {}
        self.headers = headers or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/429",
            "title": "Rate Limit Exceeded",
            "status": 429,
            "detail": self.message,
        }

        if self.retry_after:
            problem["retry_after"] = self.retry_after

        if self.limit:
            problem["limit"] = self.limit

        if self.details:
            # Only merge meaningful, non-metadata details
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem
