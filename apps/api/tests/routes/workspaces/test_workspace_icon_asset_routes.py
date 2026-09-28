# apps/api/tests/routes/workspaces/test_workspace_icon_asset_routes.py

"""Route tests for workspace icon assets."""

from collections.abc import Iterator

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from models.workspace import WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def _workspace_auth(
    db_session: AsyncSession,
    *,
    role: WorkspaceRole,
) -> tuple[dict[str, str], str]:
    user = build_user(email=f"workspace-icon-{role.value}@example.com")
    workspace = build_workspace(slug=f"workspace-icon-{role.value}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    user.default_workspace_id = workspace.id
    db_session.add_all([user, workspace, membership])
    await db_session.flush()
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()
    return bearer_headers(session["session_token"]), str(workspace.id)


async def test_workspace_icon_upload_route_requires_manager_role(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    headers, workspace_id = await _workspace_auth(db_session, role=WorkspaceRole.MEMBER)

    response = await db_async_client.post(
        f"/api/v1/workspaces/{workspace_id}/icon/upload",
        headers=headers,
        json={
            "filename": "icon.png",
            "content_type": "image/png",
            "size_bytes": 7,
        },
    )

    assert response.status_code == 403
