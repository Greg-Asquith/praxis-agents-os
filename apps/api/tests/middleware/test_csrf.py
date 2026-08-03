# apps/api/tests/middleware/test_csrf.py

"""Focused tests for CSRF middleware behavior."""

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from middleware.csrf import CSRFMiddleware
from utils.security import generate_csrf_token

ORIGIN = "http://localhost:3000"


async def _skip_security_event(
    self: CSRFMiddleware,
    request,
    *,
    reason: str,
) -> None:
    return None


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
            headers={"origin": ORIGIN},
            json={"email": "user@example.com", "password": "password"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/oauth/google/authorization-url",
        "/api/v1/auth/oauth/google/callback",
    ],
)
async def test_oauth_login_route_ignores_stale_session_cookie(path: str) -> None:
    """Pre-auth OAuth login operations remain usable with a stale session."""
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post(path)
    async def oauth_login() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set("session", "stale-session")
        client.cookies.set("csrf", generate_csrf_token("different-session"))
        response = await client.post(path, headers={"origin": ORIGIN}, json={})

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/oauth/google/link/authorization-url"),
        ("POST", "/api/v1/auth/oauth/google/link/callback"),
        ("DELETE", "/api/v1/auth/oauth/google/link"),
    ],
)
async def test_oauth_identity_mutation_requires_valid_origin_and_csrf_token(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    """Authenticated OAuth identity mutations are never CSRF-exempt."""
    monkeypatch.setattr(CSRFMiddleware, "_record_rejection", _skip_security_event)

    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.api_route(path, methods=[method])
    async def mutate_identity() -> dict[str, bool]:
        return {"ok": True}

    session_token = "current-session"
    csrf_token = generate_csrf_token(session_token)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set("session", session_token)

        missing_token = await client.request(method, path, headers={"origin": ORIGIN})
        rejected_origin = await client.request(
            method,
            path,
            headers={"origin": "https://attacker.example", "x-csrf-token": csrf_token},
        )
        accepted = await client.request(
            method,
            path,
            headers={"origin": ORIGIN, "x-csrf-token": csrf_token},
        )

    assert missing_token.status_code == 403
    assert missing_token.json()["reason"] == "X-CSRF-Token header missing"
    assert rejected_origin.status_code == 403
    assert rejected_origin.json()["reason"] == "origin not allowed"
    assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_only_put_is_exempt_for_signed_storage_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The signed-upload capability exemption is route- and method-specific."""
    monkeypatch.setattr(CSRFMiddleware, "_record_rejection", _skip_security_event)

    path = "/api/v1/storage/upload/private/runs/run-1/output.txt"
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.api_route(path, methods=["POST", "PUT"])
    async def upload() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set("session", "stale-session")
        signed_upload = await client.put(path)
        other_mutation = await client.post(path)

    assert signed_upload.status_code == 200
    assert other_mutation.status_code == 403


@pytest.mark.asyncio
async def test_authenticated_unsafe_route_rejects_mismatched_csrf_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated mutations still require a token bound to the session."""
    monkeypatch.setattr(CSRFMiddleware, "_record_rejection", _skip_security_event)

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
                "origin": ORIGIN,
                "x-csrf-token": generate_csrf_token("different-session"),
            },
        )

    assert response.status_code == 403
    assert response.json()["reason"] == "session mismatch"
