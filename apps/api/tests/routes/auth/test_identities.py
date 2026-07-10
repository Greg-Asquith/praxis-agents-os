# apps/api/tests/routes/auth/test_identities.py

"""Route tests for listing the current user's sign-in methods."""

from uuid import UUID, uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import UserAuth


async def _register(client: AsyncClient) -> UUID:
    response = await client.post(
        "/api/v1/auth/register",
        headers={"origin": "http://localhost:3000"},
        json={
            "email": f"identities-{uuid4()}@example.com",
            "password": "StrongerPassword123!",
            "display_name": "Identities User",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["user"]["id"])


@pytest.mark.asyncio
async def test_identities_reports_password_only_user(db_async_client: AsyncClient) -> None:
    await _register(db_async_client)

    response = await db_async_client.get("/api/v1/auth/me/identities")

    assert response.status_code == 200
    body = response.json()
    assert body["has_password"] is True
    assert body["identities"] == []


@pytest.mark.asyncio
async def test_identities_lists_linked_provider(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_id = await _register(db_async_client)

    db_session.add(
        UserAuth(
            user_id=user_id,
            provider="google",
            provider_user_id="google-123",
            email="identities-user@example.com",
            email_verified=True,
        )
    )
    await db_session.commit()

    response = await db_async_client.get("/api/v1/auth/me/identities")

    assert response.status_code == 200
    body = response.json()
    assert body["has_password"] is True
    assert len(body["identities"]) == 1
    identity = body["identities"][0]
    assert identity["provider"] == "google"
    assert identity["email"] == "identities-user@example.com"
    assert identity["email_verified"] is True
