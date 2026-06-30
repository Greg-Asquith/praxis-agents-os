# apps/api/tests/routes/auth/test_registration.py

"""Route tests for email/password registration."""

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_returns_auth_user_after_workspace_provisioning(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.post(
        "/api/v1/auth/register",
        headers={"origin": "http://localhost:3000"},
        json={
            "email": f"new-user-{uuid4()}@example.com",
            "password": "StrongerPassword123!",
            "display_name": "New User",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"].endswith("@example.com")
    assert body["user"]["display_name"] == "New User"
    assert body["user"]["default_workspace_id"] is not None
    assert body["user"]["updated_at"]
    assert body["session"]["twofa_verified"] is True
