# apps/api/tests/middleware/test_csrf.py

"""Focused tests for CSRF middleware behavior."""

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from middleware.csrf import CSRFMiddleware
from utils.security import generate_csrf_token


@pytest.mark.asyncio
async def test_session_creation_route_ignores_stale_session_cookie() -> None:
    """Login should not require a CSRF token from an old local session."""
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set("session", "stale-session")
        client.cookies.set("csrf", generate_csrf_token("different-session"))
        response = await client.post(
            "/api/v1/auth/login",
            headers={"origin": "http://localhost:3000"},
            json={"email": "user@example.com", "password": "password"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_authenticated_unsafe_route_rejects_mismatched_csrf_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated mutations still require a token bound to the session."""

    async def skip_security_event(
        self: CSRFMiddleware,
        request,
        *,
        reason: str,
    ) -> None:
        return None

    monkeypatch.setattr(CSRFMiddleware, "_record_rejection", skip_security_event)

    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/v1/auth/logout")
    async def logout() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set("session", "current-session")
        client.cookies.set("csrf", generate_csrf_token("different-session"))
        response = await client.post(
            "/api/v1/auth/logout",
            headers={
                "origin": "http://localhost:3000",
                "x-csrf-token": generate_csrf_token("different-session"),
            },
        )

    assert response.status_code == 403
    assert response.json()["reason"] == "session mismatch"
