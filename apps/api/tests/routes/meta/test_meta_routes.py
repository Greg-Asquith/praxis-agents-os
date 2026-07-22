"""HTTP-boundary tests for authenticated metadata routes."""

from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers


async def _authenticated_headers(db: AsyncSession) -> dict[str, str]:
    user = build_user(email=f"meta-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"meta-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return bearer_headers(session["session_token"])


async def test_openapi_schema_route_requires_authentication(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/meta/openapi.json")

    assert response.status_code == 401


async def test_openapi_schema_route_returns_schema_without_caching(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    headers = await _authenticated_headers(db_session)

    response = await db_async_client.get("/api/v1/meta/openapi.json", headers=headers)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["openapi"].startswith("3.")
    assert "/api/v1/tools/catalog" in response.json()["paths"]


async def test_anonymous_fastapi_documentation_routes_remain_disabled(
    db_async_client: AsyncClient,
) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = await db_async_client.get(path)
        assert response.status_code == 404
