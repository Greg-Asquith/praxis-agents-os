"""Production-path login rate-limit and event-loop scheduling invariants."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pyotp
import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.auth.sessions import session_manager
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
