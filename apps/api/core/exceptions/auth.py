# apps/api/core/exceptions/auth.py

"""
Custom exceptions that follow our app's error handling patterns for authentication and authorization.

These exceptions provide structured error information for auth operations and integrate with our RFC 7807 problem details format.
"""

from typing import Any

from core.exceptions._problem import PROBLEM_RESERVED_KEYS as _PROBLEM_RESERVED_KEYS

# Authentication & Authorization Errors

_INTERNAL_DETAIL_KEYS = {"membership_id", "membership_role", "user_id", "workspace_id"}


class AuthenticationError(Exception):
    """Exception for authentication failures"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/401",
            "title": "Authentication Error",
            "status": 401,
            "detail": self.message,
        }

        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem


class AuthorizationError(Exception):
    """Exception for authorization failures"""

    def __init__(
        self,
        message: str,
        required_permission: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.required_permission = required_permission
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        problem = {
            "type": "https://httpstatuses.com/403",
            "title": "Authorization Error",
            "status": 403,
            "detail": self.message,
        }

        if self.required_permission:
            problem["required_permission"] = self.required_permission

        if self.details:
            problem.update(
                {
                    k: v
                    for k, v in self.details.items()
                    if k not in _PROBLEM_RESERVED_KEYS and k not in _INTERNAL_DETAIL_KEYS
                }
            )

        return problem
