# apps/api/tests/routes/artifacts/test_platform_artifact_routes.py

"""HTTP contracts for authenticated platform Artifact management."""

from datetime import UTC, datetime
from importlib import import_module
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx2 import ASGITransport, AsyncClient

from core.database import get_async_db_session
from core.dependencies import get_current_user, get_current_workspace
from models.workspace import WorkspaceRole
from routes.artifacts import router
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


@pytest.fixture
def platform_route_context():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    actor = build_user()
    workspace = build_workspace()
    membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.READ_ONLY
    )
    db = AsyncMock()
    app.dependency_overrides[get_async_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_current_workspace] = lambda: (workspace, membership)
    return app, db, actor, workspace


@pytest.mark.parametrize(
    ("operation", "method", "path", "fields", "status"),
    [
        ("update_artifact", "PATCH", "/{id}", ("expected_current_version_id", "content"), 200),
        ("delete_artifact", "DELETE", "/{id}", (), 204),
    ],
)
async def test_platform_operations_forward_review_contract(
    platform_route_context, monkeypatch, operation, method, path, fields, status
):
    app, db, actor, workspace = platform_route_context
    artifact_id, version_id = uuid4(), uuid4()
    result = {
        "id": artifact_id,
        "scope": "platform",
        "workspace_id": None,
        "is_published": False,
        "agent_id": None,
        "conversation_id": None,
        "run_id": None,
        "current_version_id": version_id,
        "published_version_id": None,
        "artifact_type": "markdown",
        "title": "Guide",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    service = AsyncMock(return_value=None if method == "DELETE" else result)
    module = import_module(f"routes.artifacts.platform.{operation}")
    monkeypatch.setattr(module, f"{operation}_service", service)
    payload = {field: "# Guide" if field == "content" else str(uuid4()) for field in fields}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.request(
            method,
            "/api/v1/artifacts/platform" + path.format(id=artifact_id),
            json=payload if fields else None,
        )
    assert response.status_code == status
    service.assert_awaited_once()
    assert service.await_args.args == (db,)
    kwargs = service.await_args.kwargs
    assert kwargs["actor"] is actor
    assert kwargs["workspace"] is workspace
    assert kwargs["artifact_id"] == artifact_id
    if method != "GET":
        assert isinstance(kwargs["request"], Request)
    if fields:
        assert kwargs["payload"].model_dump(mode="json", exclude_unset=True) == payload
    if method == "DELETE":
        assert response.content == b""
    else:
        assert response.json()["published_version_id"] is None
        assert response.json()["workspace_id"] is None
