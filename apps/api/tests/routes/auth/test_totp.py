"""Route tests for TOTP authentication."""

from datetime import UTC, datetime

import pyotp
import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.user import User
from tests.factories import build_user
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


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
