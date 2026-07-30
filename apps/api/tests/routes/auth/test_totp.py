"""Route tests for TOTP authentication."""

# ruff: noqa: S106 - inert test passwords exercise password verification

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pyotp
import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.auth.sessions import session_manager
from core.rate_limiting import rate_limiter
from core.settings import settings
from models.session import Session
from models.user import User
from tests.factories import build_user
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _user_with_session(
    db: AsyncSession,
    *,
    email: str,
    password: str | None,
    age: timedelta = timedelta(),
) -> tuple[User, str]:
    user = build_user(email=email, password=password)
    db.add(user)
    await db.flush()
    session_result = await session_manager.create_session(db, str(user.id))
    session = await db.get(Session, UUID(session_result["session_id"]))
    assert session is not None
    session.created_at = datetime.now(UTC) - age
    await db.commit()
    return user, session_result["session_token"]


async def _totp_user_with_partial_sessions(
    db: AsyncSession,
    *,
    count: int,
    email: str = "totp-replay@example.com",
) -> tuple[User, pyotp.TOTP, list[str]]:
    user = build_user(email=email)
    secret = user.generate_totp_secret()
    user.enable_totp()
    db.add(user)
    await db.flush()
    partial_tokens = [
        (await session_manager.create_partial_session(db, str(user.id)))["session_token"]
        for _ in range(count)
    ]
    await db.commit()
    return user, pyotp.TOTP(secret), partial_tokens


async def test_totp_time_step_cannot_upgrade_two_partial_sessions(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, totp, partial_tokens = await _totp_user_with_partial_sessions(db_session, count=2)
    user_id = user.id
    counter = totp.timecode(datetime.now(UTC))
    token = totp.generate_otp(counter)

    first = await db_async_client.post(
        "/api/v1/auth/totp/verify",
        headers=bearer_headers(partial_tokens[0]),
        json={"token": token},
    )
    db_async_client.cookies.clear()
    replay = await db_async_client.post(
        "/api/v1/auth/totp/verify",
        headers=bearer_headers(partial_tokens[1]),
        json={"token": token},
    )

    assert first.status_code == 200
    assert first.json()["session"]["twofa_verified"] is True
    assert replay.status_code == 401

    db_session.expire_all()
    refreshed_user = await db_session.get(User, user_id)
    assert refreshed_user is not None
    assert refreshed_user.last_totp_counter == counter


async def test_newer_totp_time_step_remains_usable(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, totp, [partial_token] = await _totp_user_with_partial_sessions(db_session, count=1)
    current_counter = totp.timecode(datetime.now(UTC))
    user.last_totp_counter = current_counter - 1
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/auth/totp/verify",
        headers=bearer_headers(partial_token),
        json={"token": totp.generate_otp(current_counter)},
    )

    assert response.status_code == 200
    assert response.json()["session"]["twofa_verified"] is True


async def test_password_login_preserves_failure_budget_until_totp_succeeds(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    password = "correct horse battery staple"
    user = build_user(email="totp-budget-reset@example.com", password=password)
    secret = user.generate_totp_secret()
    user.enable_totp()
    user.failed_login_attempts = 2
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    login = await db_async_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )

    assert login.status_code == 200
    assert login.json()["requires_twofa"] is True
    partial_token = login.cookies["session"]
    db_async_client.cookies.clear()
    db_session.expire_all()
    password_verified_user = await db_session.get(User, user_id)
    assert password_verified_user is not None
    assert password_verified_user.failed_login_attempts == 2

    verified = await db_async_client.post(
        "/api/v1/auth/totp/verify",
        headers=bearer_headers(partial_token),
        json={"token": pyotp.TOTP(secret).now()},
    )

    assert verified.status_code == 200
    db_session.expire_all()
    fully_authenticated_user = await db_session.get(User, user_id)
    assert fully_authenticated_user is not None
    assert fully_authenticated_user.failed_login_attempts == 0


async def test_totp_failure_budget_revokes_all_partial_sessions(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SECURITY_SUSPICIOUS_ACTIVITY_THRESHOLD", 3)
    monkeypatch.setattr(rate_limiter, "enabled", False)
    async with committed_db_session_factory() as setup_db:
        user, totp, partial_tokens = await _totp_user_with_partial_sessions(
            setup_db,
            count=3,
            email=f"totp-budget-{uuid4()}@example.com",
        )
        user_id = user.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for partial_token in partial_tokens:
            response = await client.post(
                "/api/v1/auth/totp/verify",
                headers=bearer_headers(partial_token),
                json={"token": "000000"},
            )
            assert response.status_code == 401

        blocked = await client.post(
            "/api/v1/auth/totp/verify",
            headers=bearer_headers(partial_tokens[-1]),
            json={"token": totp.now()},
        )

        assert blocked.status_code == 401

    async with committed_db_session_factory() as verify_db:
        refreshed_user = await verify_db.get(User, user_id)
        assert refreshed_user is not None
        assert refreshed_user.failed_login_attempts == 3
        assert refreshed_user.is_locked


async def test_stale_session_cannot_start_or_complete_totp_enrollment(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, session_token = await _user_with_session(
        db_session,
        email="stale-totp-enrollment@example.com",
        password="correct horse battery staple",
        age=timedelta(minutes=30),
    )

    setup_response = await db_async_client.post(
        "/api/v1/auth/totp/setup",
        headers=bearer_headers(session_token),
        json={},
    )

    assert setup_response.status_code == 401
    await db_session.refresh(user)
    assert user.totp_secret_encrypted is None

    secret = user.generate_totp_secret()
    await db_session.commit()
    enable_response = await db_async_client.post(
        "/api/v1/auth/totp/enable",
        headers=bearer_headers(session_token),
        json={
            "enrollment_token": "attacker-controlled",
            "token": pyotp.TOTP(secret).now(),
        },
    )

    assert enable_response.status_code == 401
    await db_session.refresh(user)
    assert user.totp_enabled is False


async def test_password_step_up_grant_enables_totp_for_stale_session(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, session_token = await _user_with_session(
        db_session,
        email="password-step-up@example.com",
        password="correct horse battery staple",
        age=timedelta(minutes=30),
    )

    setup_response = await db_async_client.post(
        "/api/v1/auth/totp/setup",
        headers=bearer_headers(session_token),
        json={"current_password": "correct horse battery staple"},
    )

    assert setup_response.status_code == 200
    setup = setup_response.json()
    enable_response = await db_async_client.post(
        "/api/v1/auth/totp/enable",
        headers=bearer_headers(session_token),
        json={
            "enrollment_token": setup["enrollment_token"],
            "token": pyotp.TOTP(setup["secret"]).now(),
        },
    )

    assert enable_response.status_code == 200
    assert len(enable_response.json()["backup_codes"]) == 8
    await db_session.refresh(user)
    assert user.totp_enabled is True


async def test_recent_full_session_allows_passwordless_totp_enrollment(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _, session_token = await _user_with_session(
        db_session,
        email="recent-oauth-totp@example.com",
        password=None,
    )

    response = await db_async_client.post(
        "/api/v1/auth/totp/setup",
        headers=bearer_headers(session_token),
        json={},
    )

    assert response.status_code == 200
    assert response.json()["enrollment_token"]
