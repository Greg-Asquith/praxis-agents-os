"""Production-path login rate-limit and event-loop scheduling invariants."""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pyotp
import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import utils.security as security_module
from core.auth.sessions import session_manager
from core.exceptions.general import ConflictError
from core.rate_limiting import rate_limiter
from core.settings import settings
from models.rate_limiting import RateLimitAttempt
from models.security import SecurityEvent
from services.security import SecurityEventType
from tests.factories import build_user
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio
ORIGIN = "http://localhost:3000"


@asynccontextmanager
async def _app_client(
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    address_groups = [uuid4().hex[index : index + 4] for index in range(0, 16, 4)]
    client_ip = f"2001:db8:{':'.join(address_groups)}::1"
    request_id = uuid4().hex
    transport = ASGITransport(
        app=app,
        client=(client_ip, 123),
    )
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"origin": ORIGIN, "x-request-id": request_id},
        ) as client:
            yield client
    finally:
        async with session_factory() as cleanup_db:
            await cleanup_db.execute(
                delete(SecurityEvent).where(SecurityEvent.ip_address == client_ip)
            )
            await cleanup_db.execute(
                delete(RateLimitAttempt).where(RateLimitAttempt.ip_address == client_ip)
            )
            await cleanup_db.commit()


async def test_successful_logins_do_not_consume_failed_login_budget(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", True)
    monkeypatch.setitem(rate_limiter.default_limits, "login_attempts", (5, 3600))
    password = "correct horse battery staple"
    user = build_user(email=f"successful-logins-{uuid4()}@example.com", password=password)
    async with committed_db_session_factory() as setup_db:
        setup_db.add(user)
        await setup_db.commit()

    statuses = []
    async with _app_client(app, committed_db_session_factory) as client:
        for _ in range(6):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": password},
            )
            statuses.append(response.status_code)
            client.cookies.clear()

    assert statuses == [200, 200, 200, 200, 200, 200]


async def test_five_failures_block_only_the_same_client_and_account(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", True)
    monkeypatch.setitem(rate_limiter.default_limits, "login_attempts", (5, 3600))
    target_email = f"target-{uuid4()}@example.com"
    other_email = f"other-{uuid4()}@example.com"
    failed_statuses = []
    async with _app_client(app, committed_db_session_factory) as client:
        for _ in range(5):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": target_email, "password": "wrong"},
            )
            failed_statuses.append(response.status_code)
        blocked = await client.post(
            "/api/v1/auth/login",
            json={"email": target_email.upper(), "password": "wrong"},
        )
        different_account = await client.post(
            "/api/v1/auth/login",
            json={"email": other_email, "password": "wrong"},
        )

    assert failed_statuses == [401, 401, 401, 401, 401]
    assert blocked.status_code == 429
    assert different_account.status_code == 401


async def test_failures_for_different_accounts_do_not_share_a_budget(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", True)
    monkeypatch.setitem(rate_limiter.default_limits, "login_attempts", (5, 3600))
    statuses = []
    run_id = uuid4()
    async with _app_client(app, committed_db_session_factory) as client:
        for index in range(6):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": f"account-{run_id}-{index}@example.com", "password": "wrong"},
            )
            statuses.append(response.status_code)

    assert statuses == [401, 401, 401, 401, 401, 401]


async def test_password_login_keeps_the_event_loop_responsive(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", True)
    user = build_user(email=f"async-password-{uuid4()}@example.com")
    user.password_hash = "test-password-hash"
    async with committed_db_session_factory() as setup_db:
        setup_db.add(user)
        await setup_db.commit()

    def slow_verification(_plain_password: str, _hashed_password: str) -> bool:
        time.sleep(0.2)
        return True

    monkeypatch.setattr(security_module, "verify_password_hash", slow_verification)
    stop_ticker = asyncio.Event()
    scheduling_delays: list[float] = []

    async def record_scheduling_delays() -> None:
        previous = time.perf_counter()
        while not stop_ticker.is_set():
            await asyncio.sleep(0.002)
            current = time.perf_counter()
            scheduling_delays.append(current - previous)
            previous = current

    ticker = asyncio.create_task(record_scheduling_delays())
    await asyncio.sleep(0)
    async with _app_client(app, committed_db_session_factory) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "correct password"},
        )
    stop_ticker.set()
    await ticker

    assert response.status_code == 200
    assert len(scheduling_delays) > 10
    assert max(scheduling_delays) < 0.1


async def test_anonymous_totp_failures_do_not_block_a_resolved_account(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(rate_limiter.default_limits, "login_attempts", (2, 3600))
    user = build_user(email=f"totp-anonymous-budget-{uuid4()}@example.com")
    secret = user.generate_totp_secret()
    user.enable_totp()
    async with committed_db_session_factory() as setup_db:
        setup_db.add(user)
        await setup_db.flush()
        partial_session = await session_manager.create_partial_session(setup_db, str(user.id))
        await setup_db.commit()

    async with _app_client(app, committed_db_session_factory) as client:
        failures = [
            await client.post("/api/v1/auth/totp/verify", json={"token": "000000"})
            for _ in range(3)
        ]
        verified = await client.post(
            "/api/v1/auth/totp/verify",
            headers=bearer_headers(partial_session["session_token"]),
            json={"token": pyotp.TOTP(secret).now()},
        )
        async with committed_db_session_factory() as audit_db:
            rate_limit_event = await audit_db.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.request_id == client.headers["x-request-id"],
                    SecurityEvent.event_type == SecurityEventType.RATE_LIMIT_EXCEEDED,
                )
                .order_by(SecurityEvent.occurred_at.desc())
                .limit(1)
            )

    assert [response.status_code for response in failures] == [401, 401, 429]
    assert verified.status_code == 200
    assert failures[-1].json()["rate_limit"]["type"] == "login_attempts"
    assert isinstance(failures[-1].json()["rate_limit"]["reset"], int)
    assert rate_limit_event is not None
    assert rate_limit_event.details["limit_type"] == "login_attempts"


async def test_oauth_known_account_failures_enforce_the_account_budget(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(rate_limiter.default_limits, "login_attempts", (2, 3600))
    account_email = f"oauth-collision-{uuid4()}@example.com"
    provider = type(
        "Provider",
        (),
        {
            "exchange_code": AsyncMock(return_value={"access_token": "provider-token"}),
            "get_user_info": AsyncMock(
                return_value={
                    "sub": "provider-user",
                    "email": account_email,
                    "email_verified": True,
                }
            ),
        },
    )()
    upsert_oauth_user = AsyncMock(
        side_effect=ConflictError(
            "An account with this email already exists",
            conflicting_resource="user_auth",
            details={"reason": "oauth_email_collision"},
        )
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.oauth_registry.get_provider",
        lambda _provider_name: provider,
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.verify_oauth_state",
        lambda _state: {
            "provider": "google",
            "redirect_uri": "https://app.example/oauth/callback",
            "next_path": None,
        },
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.verify_oauth_login_browser_binding",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.resolve_provider_redirect_uri",
        lambda *_args, **_kwargs: "https://app.example/oauth/callback",
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.upsert_oauth_user",
        upsert_oauth_user,
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_login.record_auth_security_event",
        AsyncMock(),
    )

    async with _app_client(app, committed_db_session_factory) as client:
        responses = [
            await client.post(
                "/api/v1/auth/oauth/google/callback",
                json={
                    "code": "provider-code",
                    "state": "signed-state",
                    "redirect_uri": "https://app.example/oauth/callback",
                },
            )
            for _ in range(3)
        ]
        async with committed_db_session_factory() as audit_db:
            rate_limit_event = await audit_db.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.request_id == client.headers["x-request-id"],
                    SecurityEvent.event_type == SecurityEventType.RATE_LIMIT_EXCEEDED,
                )
                .order_by(SecurityEvent.occurred_at.desc())
                .limit(1)
            )

    assert [response.status_code for response in responses] == [409, 409, 429]
    assert upsert_oauth_user.await_count == 2
    assert responses[-1].json()["rate_limit"]["type"] == "login_attempts"
    assert isinstance(responses[-1].json()["rate_limit"]["reset"], int)
    assert rate_limit_event is not None
    assert rate_limit_event.user_email == account_email
