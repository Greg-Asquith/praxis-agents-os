# apps/api/tests/middleware/test_rate_limit.py

"""Focused tests for rate-limit middleware behavior."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

import middleware.rate_limit as rate_limit_module
from core.rate_limiting import RateLimitResult
from middleware.rate_limit import RateLimitMiddleware


def test_totp_and_oauth_login_callback_use_auth_critical_rate_limit() -> None:
    middleware = RateLimitMiddleware(FastAPI())

    assert middleware._get_limit_type("/api/v1/auth/totp/verify", "POST") == "login_attempts"
    assert middleware._get_limit_type("/api/v1/auth/oauth/google/callback", "POST") == (
        "login_attempts"
    )


@pytest.mark.asyncio
async def test_auth_path_fails_closed_when_limiter_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_limiter_error(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        rate_limit_module,
        "get_login_failure_status",
        raise_limiter_error,
    )

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "rate-limit@example.com", "password": "inert"},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_general_budget_is_enforced_without_a_database_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse_session_factory():
        raise AssertionError("general requests must not open a database session")

    recorded_events: list[dict] = []

    async def record_event(**kwargs):
        recorded_events.append(kwargs)

    monkeypatch.setattr(rate_limit_module, "get_async_db_session_factory", refuse_session_factory)
    monkeypatch.setattr(rate_limit_module, "safe_record_security_event_committed", record_event)
    monkeypatch.setitem(
        rate_limit_module.rate_limiter.default_limits, "requests_per_minute", (2, 60)
    )

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/v1/status")
    async def status() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = [await client.get("/api/v1/status") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[1].headers["X-RateLimit-Remaining"] == "0"
    assert recorded_events[0]["details"]["limit_type"] == "requests_per_minute"


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

    monkeypatch.setattr(rate_limit_module, "get_login_failure_status", deny_request)
    monkeypatch.setattr(rate_limit_module, "safe_record_security_event", skip_security_event)

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "rate-limit@example.com", "password": "inert"},
        )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.json()["rate_limit"]["type"] == "login_attempts"


@pytest.mark.asyncio
async def test_hourly_window_is_enforced_alongside_minute_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def skip_security_event(**kwargs):
        return None

    monkeypatch.setattr(
        rate_limit_module, "safe_record_security_event_committed", skip_security_event
    )
    monkeypatch.setitem(
        rate_limit_module.rate_limiter.default_limits, "requests_per_hour", (1, 3600)
    )

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/v1/status")
    async def status() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/api/v1/status")).status_code == 200
        response = await client.get("/api/v1/status")

    assert response.status_code == 429
    assert response.json()["rate_limit"]["type"] == "requests_per_hour"
