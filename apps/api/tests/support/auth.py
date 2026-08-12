# apps/api/tests/support/auth.py
"""Auth-specific helpers for API tests."""

import pytest

from core.settings import settings

SESSION_COOKIE_NAME = "session"
CSRF_COOKIE_NAME = "csrf"
CSRF_HEADER_NAME = "x-csrf-token"

requires_email_auth = pytest.mark.skipif(
    not settings.EMAIL_AUTH_ENABLED,
    reason="email/password authentication is disabled",
)


def bearer_headers(token: str) -> dict[str, str]:
    """Build Authorization headers for bearer-token tests."""
    return {"Authorization": f"Bearer {token}"}


def csrf_headers(token: str) -> dict[str, str]:
    """Build CSRF headers for state-changing request tests."""
    return {CSRF_HEADER_NAME: token}


def session_cookies(session_token: str, csrf_token: str | None = None) -> dict[str, str]:
    """Build session cookies for tests that exercise authenticated routes."""
    cookies = {SESSION_COOKIE_NAME: session_token}
    if csrf_token is not None:
        cookies[CSRF_COOKIE_NAME] = csrf_token
    return cookies
