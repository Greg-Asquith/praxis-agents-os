# apps/api/tests/support/auth.py
"""Auth-specific helpers for API tests."""

import pytest

from core.settings import settings

requires_email_auth = pytest.mark.skipif(
    not settings.EMAIL_AUTH_ENABLED,
    reason="email/password authentication is disabled",
)


def bearer_headers(token: str) -> dict[str, str]:
    """Build Authorization headers for bearer-token tests."""
    return {"Authorization": f"Bearer {token}"}
