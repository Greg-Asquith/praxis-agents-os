# apps/api/core/exceptions/oauth.py

"""
Custom exceptions that follow our app's error handling patterns for OAuth operations.

These exceptions provide structured error information for OAuth operations and integrate with our RFC 7807 problem details format.
"""

from typing import Any

from core.exceptions._problem import PROBLEM_RESERVED_KEYS as _PROBLEM_RESERVED_KEYS

# OAuth Errors


class OAuthError(Exception):
    """Base exception for OAuth-related errors"""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        endpoint: str | None = None,
        status_code: int | None = None,
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.endpoint = endpoint
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}

    def to_problem_details(self) -> dict[str, Any]:
        """Convert to RFC 7807 problem details format"""
        status = self.status_code or 500
        problem = {
            "type": f"https://httpstatuses.com/{status}",
            "title": "OAuth Error",
            "status": status,
            "detail": self.message,
        }

        if self.provider:
            problem["provider"] = self.provider

        if self.endpoint:
            problem["endpoint"] = self.endpoint

        if self.details:
            problem.update(
                {k: v for k, v in self.details.items() if k not in _PROBLEM_RESERVED_KEYS}
            )

        return problem


class OAuthProviderError(OAuthError):
    """Exception for OAuth provider-specific errors"""

    def __init__(
        self,
        message: str,
        provider: str,
        endpoint: str | None = None,
        status_code: int | None = None,
        retryable: bool = True,
    ):
        super().__init__(
            message=message,
            provider=provider,
            endpoint=endpoint,
            status_code=status_code,
            retryable=retryable,
        )

    def to_problem_details(self) -> dict[str, Any]:
        problem = super().to_problem_details()
        problem["title"] = f"{self.provider.title()} OAuth Error"
        return problem


class OAuthNetworkError(OAuthProviderError):
    """Exception for OAuth network-related errors"""

    def __init__(self, message: str, provider: str, endpoint: str | None = None):
        super().__init__(
            message=message,
            provider=provider,
            endpoint=endpoint,
            status_code=503,  # Service Unavailable
            retryable=True,
        )

    def to_problem_details(self) -> dict[str, Any]:
        problem = super().to_problem_details()
        problem["title"] = f"{self.provider.title()} OAuth Network Error"
        return problem


class OAuthAuthenticationError(OAuthProviderError):
    """Exception for OAuth authentication failures"""

    def __init__(self, message: str, provider: str, endpoint: str | None = None):
        super().__init__(
            message=message,
            provider=provider,
            endpoint=endpoint,
            status_code=401,  # Unauthorized
            retryable=False,  # Auth errors usually aren't retryable
        )

    def to_problem_details(self) -> dict[str, Any]:
        problem = super().to_problem_details()
        problem["title"] = f"{self.provider.title()} OAuth Authentication Error"
        return problem


class OAuthConfigurationError(OAuthError):
    """Exception for OAuth configuration issues"""

    def __init__(self, message: str, provider: str | None = None):
        super().__init__(message=message, provider=provider, status_code=500, retryable=False)

    def to_problem_details(self) -> dict[str, Any]:
        problem = super().to_problem_details()
        problem["title"] = "OAuth Configuration Error"
        return problem
