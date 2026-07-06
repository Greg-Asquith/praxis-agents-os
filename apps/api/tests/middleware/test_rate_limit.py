"""Focused tests for rate-limit middleware behavior."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import middleware.rate_limit as rate_limit_module
from core.rate_limiting import RateLimitResult
from middleware.rate_limit import RateLimitMiddleware


@pytest.mark.asyncio
async def test_auth_path_fails_closed_when_limiter_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_limiter_error(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        rate_limit_module.rate_limiter,
        "check_rate_limit",
        raise_limiter_error,
    )

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/auth/login")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_general_path_passes_through_when_limiter_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_limiter_error(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        rate_limit_module.rate_limiter,
        "check_rate_limit",
        raise_limiter_error,
    )

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/v1/status")
    async def status() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/status")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_blocked_response_includes_retry_and_rate_limit_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = RateLimitResult(
        allowed=False,
        attempts=4,
        limit=3,
        window_seconds=60,
        reset_time=datetime.now(UTC) + timedelta(seconds=30),
        retry_after=30,
    )

    async def deny_request(*args, **kwargs):
        return denied

    async def skip_security_event(*args, **kwargs):
        return None

    monkeypatch.setattr(rate_limit_module.rate_limiter, "check_rate_limit", deny_request)
    monkeypatch.setattr(rate_limit_module, "safe_record_security_event", skip_security_event)

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/auth/login")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.json()["rate_limit"]["type"] == "login_attempts"
