# apps/api/tests/routes/auth/test_oauth_link.py

"""Tests for unlinking OAuth providers from the current user."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.user import UserAuth
from services.auth.oauth.unlink_oauth_provider import unlink_oauth_provider
from tests.factories.users import build_user

ORIGIN = "http://localhost:3000"


async def _register(client: AsyncClient) -> UUID:
    response = await client.post(
        "/api/v1/auth/register",
        headers={"origin": ORIGIN},
        json={
            "email": f"link-{uuid4()}@example.com",
            "password": "StrongerPassword123!",
            "display_name": "Link User",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["user"]["id"])


def _state_changing_headers(client: AsyncClient) -> dict[str, str]:
    return {"origin": ORIGIN, "x-csrf-token": client.cookies.get("csrf", "")}


@pytest.mark.asyncio
async def test_unlink_removes_provider_when_password_remains(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_id = await _register(db_async_client)
    db_session.add(
        UserAuth(
            user_id=user_id,
            provider="google",
            provider_user_id="google-unlink-1",
            email="link-user@example.com",
            email_verified=True,
        )
    )
    await db_session.commit()

    response = await db_async_client.request(
        "DELETE",
        "/api/v1/auth/oauth/google/link",
        headers=_state_changing_headers(db_async_client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_password"] is True
    assert body["identities"] == []


@pytest.mark.asyncio
async def test_unlink_unknown_provider_returns_404(db_async_client: AsyncClient) -> None:
    await _register(db_async_client)

    response = await db_async_client.request(
        "DELETE",
        "/api/v1/auth/oauth/github/link",
        headers=_state_changing_headers(db_async_client),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unlink_only_sign_in_method_is_rejected(db_session: AsyncSession) -> None:
    user = build_user(email=f"only-{uuid4()}@example.com", password=None)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserAuth(
            user_id=user.id,
            provider="google",
            provider_user_id="google-only-1",
            email=user.email,
            email_verified=True,
        )
    )
    await db_session.flush()

    with pytest.raises(ConflictError):
        await unlink_oauth_provider(
            db_session,
            request=SimpleNamespace(),
            user=user,
            provider_name="google",
        )


@pytest.mark.asyncio
async def test_unlink_missing_provider_at_service_layer(db_session: AsyncSession) -> None:
    strong_password = "StrongerPassword123!"
    user = build_user(email=f"nopass-{uuid4()}@example.com", password=strong_password)
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(NotFoundError):
        await unlink_oauth_provider(
            db_session,
            request=SimpleNamespace(),
            user=user,
            provider_name="google",
        )
