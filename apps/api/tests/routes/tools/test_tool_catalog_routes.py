# apps/api/tests/routes/tools/test_tool_cataloy_routes.py

"""HTTP-boundary tests for runtime tool catalog routes."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.READ_ONLY,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"tools-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"tools-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return user, workspace, bearer_headers(session["session_token"])


async def test_tool_catalog_route_returns_core_entries_for_workspace_member(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get("/api/v1/tools/catalog", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["tools"] == [
        {
            "name": "add_numbers",
            "provider": "core",
            "label": "Add numbers",
            "description": "Add two integers.",
            "effect": "read",
            "default_policy": "auto",
            "supported_policies": ["approval", "auto"],
            "defer_loading": False,
        },
        {
            "name": "get_runtime_context",
            "provider": "core",
            "label": "Runtime context",
            "description": (
                "Read the current Praxis workspace, conversation, agent, and run identifiers."
            ),
            "effect": "read",
            "default_policy": "approval",
            "supported_policies": ["approval", "auto"],
            "defer_loading": False,
        },
    ]
    assert "timeout" not in body["tools"][0]
    assert "max_retries" not in body["tools"][0]
    assert "output_model" not in body["tools"][0]


async def test_tool_catalog_route_requires_authentication(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/tools/catalog")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
