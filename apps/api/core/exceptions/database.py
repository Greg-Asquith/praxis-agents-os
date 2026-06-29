# apps/api/core/exceptions/database.py

"""
Custom exceptions that follow our app's error handling patterns for database operations.

These exceptions provide structured error information for database operations and integrate with our RFC 7807 problem details format.
"""

from typing import Any

from core.exceptions._problem import PROBLEM_RESERVED_KEYS as _PROBLEM_RESERVED_KEYS

# Database Errors


class DatabaseError(Exception):
    """Exception for database operations"""

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.operation = operation
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/500",
            "title": "Database Error",
            "status": 500,
            "detail": self.message,
        }

        if self.operation:
            problem["operation"] = self.operation

        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem
