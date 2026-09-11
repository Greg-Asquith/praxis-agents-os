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
from services.artifacts.platform.schemas import PlatformArtifactListResponse
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
        (
            "create_artifact",
            "POST",
            "/from-workspace/{id}",
            ("expected_current_version_id", "version_id", "request_id"),
            201,
        ),
        ("update_artifact", "PATCH", "/{id}", ("expected_current_version_id", "content"), 200),
        (
            "restore_artifact_version",
            "POST",
            "/{id}/restore",
            ("expected_current_version_id", "version_id"),
            200,
        ),
        ("publish_artifact", "POST", "/{id}/publish", ("expected_current_version_id",), 200),
        ("withdraw_artifact", "POST", "/{id}/withdraw", (), 200),
        ("delete_artifact", "DELETE", "/{id}", (), 204),
        ("get_artifact", "GET", "/{id}", (), 200),
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


async def test_platform_list_precedes_workspace_id_and_bounds_pagination(
    platform_route_context, monkeypatch
):
    app, db, actor, workspace = platform_route_context
    empty = PlatformArtifactListResponse(items=[], total=0, limit=50, offset=0)
    service = AsyncMock(return_value=empty)
    monkeypatch.setattr(
        import_module("routes.artifacts.platform.list_artifacts"), "list_artifacts_service", service
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/artifacts/platform/")
        for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
            invalid = await client.get("/api/v1/artifacts/platform/", params=params)
            assert invalid.status_code == 422
    assert response.status_code == 200
    assert response.json() == empty.model_dump(mode="json")
    service.assert_awaited_once_with(db, actor=actor, workspace=workspace, limit=50, offset=0)


async def test_platform_content_forwards_selected_version(platform_route_context, monkeypatch):
    app, db, actor, workspace = platform_route_context
    artifact_id, version_id = uuid4(), uuid4()
    service = AsyncMock(
        return_value={"content": "# Guide", "content_type": "text/markdown", "size_bytes": 7}
    )
    monkeypatch.setattr(
        import_module("routes.artifacts.platform.get_version_content"),
        "get_version_content_service",
        service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/artifacts/platform/{artifact_id}/content",
            params={"version_id": str(version_id)},
        )
    assert response.status_code == 200
    assert response.json()["content"] == "# Guide"
    assert response.headers["cache-control"] == "private, no-store"
    service.assert_awaited_once_with(
        db, actor=actor, workspace=workspace, artifact_id=artifact_id, version_id=version_id
    )


@pytest.mark.parametrize(
    ("operation", "method", "path", "payload"),
    [
        ("create_artifact", "POST", "/from-workspace/{id}", {"version_id": str(uuid4())}),
        ("update_artifact", "PATCH", "/{id}", {"content": "# Guide"}),
        ("restore_artifact_version", "POST", "/{id}/restore", {"version_id": str(uuid4())}),
        (
            "publish_artifact",
            "POST",
            "/{id}/publish",
            {"expected_current_version_id": str(uuid4()), "is_published": True},
        ),
    ],
)
async def test_review_payload_requires_concurrency_and_rejects_extra_fields(
    platform_route_context, monkeypatch, operation, method, path, payload
):
    app, *_ = platform_route_context
    service = AsyncMock()
    monkeypatch.setattr(
        import_module(f"routes.artifacts.platform.{operation}"), f"{operation}_service", service
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.request(
            method, "/api/v1/artifacts/platform" + path.format(id=uuid4()), json=payload
        )
    assert response.status_code == 422
    service.assert_not_awaited()
