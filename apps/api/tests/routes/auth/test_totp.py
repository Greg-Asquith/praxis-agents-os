"""Route tests for TOTP authentication."""

# ruff: noqa: S106 - inert test passwords exercise password verification

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pyotp
import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
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
) -> tuple[User, pyotp.TOTP, list[str]]:
    user = build_user(email="totp-replay@example.com")
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
