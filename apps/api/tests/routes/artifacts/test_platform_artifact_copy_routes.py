# apps/api/tests/routes/artifacts/test_platform_artifact_copy_routes.py

"""HTTP copy requests create local Artifacts only for active workspace editors."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from core.database import (
    get_async_db_session,
    maintenance_async_db_session,
    set_session_tenant_context,
)
from core.dependencies import get_current_user, get_current_workspace
from core.exceptions.exception_handlers import register_exception_handlers
from models.workspace import WorkspaceMembership, WorkspaceRole
from routes.artifacts import router
from tests.support.platform_artifacts import (
    committed_artifact_context as committed_artifact_context,
    platform_copy_context as platform_copy_context,
)


@pytest.fixture
async def copy_app(committed_db_session_factory, platform_copy_context):
    context, membership_id, _artifact, _payload = platform_copy_context
    async with maintenance_async_db_session() as db:
        membership = await db.get(WorkspaceMembership, membership_id)

    async def session():
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db, workspace_id=context["workspace"].id, user_id=context["actor"].id
            )
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    register_exception_handlers(app)
    app.dependency_overrides[get_async_db_session] = session
    app.dependency_overrides[get_current_user] = lambda: context["actor"]
    app.dependency_overrides[get_current_workspace] = lambda: (context["workspace"], membership)
    return app, membership


@pytest.mark.parametrize(
    "role",
    [WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.MEMBER, WorkspaceRole.READ_ONLY],
)
async def test_platform_copy_http_enforces_editor_access(copy_app, platform_copy_context, role):
    app, membership = copy_app
    context, membership_id, artifact, payload = platform_copy_context
    membership.role = role
    async with maintenance_async_db_session() as db:
        (await db.get(WorkspaceMembership, membership_id)).role = role
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/artifacts/{artifact.id}/copy", json=payload.model_dump(mode="json")
        )
    if role == WorkspaceRole.READ_ONLY:
        assert response.status_code == 403
    else:
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["scope"] == "workspace"
        assert result["workspace_id"] == str(context["workspace"].id)
        assert result["id"] != str(artifact.id)
        assert result["can_edit"] is True
        assert len(result["versions"]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"version_id": str(uuid4())},
        {"request_id": str(uuid4())},
        {"version_id": str(uuid4()), "request_id": str(uuid4()), "scope": "platform"},
    ],
)
async def test_platform_copy_http_requires_exact_pin_and_request_identity(
    copy_app, platform_copy_context, payload
):
    app, _membership = copy_app
    _context, _membership_id, artifact, _request = platform_copy_context
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(f"/api/v1/artifacts/{artifact.id}/copy", json=payload)
    assert response.status_code == 422
