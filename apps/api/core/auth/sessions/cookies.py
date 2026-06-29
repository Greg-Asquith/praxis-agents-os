# apps/api/core/auth/sessions/cookies.py

"""Session cookie helpers."""

from datetime import UTC, datetime
from typing import Any

from core.settings import settings


class SessionCookieMixin:
    """Create, set, and clear session cookies."""

    def create_session_cookie(self, session_token: str, expires_at: datetime) -> dict[str, Any]:
        """
        Create cookie configuration for session token.

        Args:
            session_token: Raw session token
            expires_at: Session expiration datetime

        Returns:
            Cookie configuration dictionary
        """
        return {
            "key": "session",
            "value": session_token,
            "expires": expires_at,
            "httponly": True,
            "secure": settings.SECURE_COOKIES,
            "domain": settings.COOKIE_DOMAIN,
            "samesite": "lax",
            "path": "/",
        }

    def set_session_cookie(
        self, response, session_token: str, expires_at: datetime | None = None
    ) -> None:
        """
        Attach the session cookie to a FastAPI Response.

        Args:
            response: FastAPI Response object
            session_token: Raw session token
            expires_at: Expiration datetime; if None, use default duration from now
        """
        exp = expires_at or (datetime.now(UTC) + self.default_session_duration)
        cfg = self.create_session_cookie(
            session_token=session_token,
            expires_at=exp,
        )
        # FastAPI Response.set_cookie signature matches our dict
        response.set_cookie(**cfg)

    def clear_session_cookie(self, response) -> None:
        """Remove the session cookie, matching the attributes it was set with."""
        response.delete_cookie(
            "session",
            domain=settings.COOKIE_DOMAIN or None,
            path="/",
            samesite="lax",
            secure=settings.SECURE_COOKIES,
            httponly=True,
        )
