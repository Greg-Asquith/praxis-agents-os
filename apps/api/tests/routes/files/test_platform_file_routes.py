# apps/api/tests/routes/files/test_platform_file_routes.py

"""HTTP contracts for authenticated platform File management."""

from importlib import import_module
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from core.database import get_async_db_session
from core.dependencies import get_current_user, get_current_workspace
from models.workspace import WorkspaceRole
from routes.files import router
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


@pytest.fixture
def platform_route_app():
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
    return app, db, actor


async def test_platform_preview_returns_bytes_with_restrictive_headers(
    platform_route_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, db, actor = platform_route_app
    file_id, revision_id = uuid4(), uuid4()
    content = b"<script>alert(1)</script>"
    service = AsyncMock(return_value=(content, "text/html"))
    module = import_module("routes.files.platform.get_file_preview")
    monkeypatch.setattr(module, "get_file_preview_service", service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/api/v1/files/platform/{file_id}/preview", params={"revision_id": str(revision_id)}
        )
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    service.assert_awaited_once_with(db, actor=actor, file_id=file_id, revision_id=revision_id)


async def test_platform_list_precedes_workspace_file_id_and_bounds_pagination(
    platform_route_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, db, actor = platform_route_app
    service = AsyncMock(return_value={"files": [], "total": 0})
    module = import_module("routes.files.platform.list_files")
    monkeypatch.setattr(module, "list_files_service", service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/files/platform/")
        invalid = await client.get("/api/v1/files/platform/", params={"limit": 101})
    assert response.status_code == 200
    assert response.json() == {"files": [], "total": 0}
    assert invalid.status_code == 422
    service.assert_awaited_once_with(db, actor=actor, limit=50, offset=0)


async def test_platform_upload_passes_explicit_scope(
    platform_route_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from services.files.domain import FileUploadRequest
    from utils.content import ContentScope

    app, db, actor = platform_route_app
    file_id = uuid4()
    service = AsyncMock(
        return_value={
            "deduplicated": False,
            "grant": {
                "upload": {
                    "ref": {"bucket": "platform_private", "key": "platform/uploads/guide.txt"},
                    "url": "http://testserver/upload",
                    "method": "PUT",
                    "headers": {},
                    "expires_at": datetime.now(UTC),
                },
                "upload_token": "platform-grant",
                "max_size_bytes": 1024,
                "expires_at": datetime.now(UTC),
                "file_id": file_id,
            },
        }
    )
    module = import_module("routes.files.platform.create_file_upload")
    monkeypatch.setattr(module, "create_upload_service", service)
    payload = {"filename": "guide.txt", "content_type": "text/plain", "size_bytes": 5}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/v1/files/platform/uploads", json=payload)
    assert response.status_code == 200
    assert response.json()["grant"]["file_id"] == str(file_id)
    service.assert_awaited_once()
    assert service.await_args.args == (db,)
    assert service.await_args.kwargs["actor"] is actor
    assert service.await_args.kwargs["membership"].role == WorkspaceRole.READ_ONLY
    assert service.await_args.kwargs["scope"] == ContentScope.PLATFORM
    assert service.await_args.kwargs["payload"] == FileUploadRequest(**payload)
