# apps/api/tests/routes/kb/test_platform_knowledge_routes.py

"""Platform knowledge HTTP routing and ownership input boundaries."""

from importlib import import_module
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from core.database import get_async_db_session
from core.dependencies import get_current_user, get_current_workspace
from models.workspace import WorkspaceRole
from routes.kb import router
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


@pytest.fixture
def platform_app():
    app = FastAPI()
    app.include_router(router)
    actor, workspace, db = build_user(), build_workspace(), AsyncMock()
    membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.READ_ONLY
    )
    app.dependency_overrides[get_async_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_current_workspace] = lambda: (workspace, membership)
    return app, db, actor


async def test_platform_knowledge_list_accepts_read_only_membership_and_bounds_page(
    platform_app, monkeypatch
):
    app, db, actor = platform_app
    service = AsyncMock(return_value={"documents": [], "total": 0, "limit": 50, "offset": 0})
    monkeypatch.setattr(import_module("routes.kb.platform.list_documents"), "service", service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/kb/platform/documents/")
        invalid = await client.get("/kb/platform/documents/?limit=101")
    assert response.status_code == 200 and invalid.status_code == 422
    service.assert_awaited_once_with(db, actor=actor, limit=50, offset=0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "workspace"),
        ("workspace_id", str(uuid4())),
        ("is_published", True),
        ("is_private", True),
    ],
)
async def test_platform_knowledge_create_refuses_ownership_and_publication_input(
    platform_app, monkeypatch, field, value
):
    app, _, _ = platform_app
    service = AsyncMock()
    monkeypatch.setattr(
        import_module("routes.kb.platform.create_manual_document"), "service", service
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/kb/platform/documents/",
            json={"title": "Policy", "content_md": "Policy", field: value},
        )
    assert response.status_code == 422
    service.assert_not_awaited()


async def test_platform_knowledge_delete_retains_platform_service_authority(
    platform_app, monkeypatch
):
    app, db, actor = platform_app
    service = AsyncMock()
    monkeypatch.setattr(import_module("routes.kb.platform.delete_document"), "service", service)
    document_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(f"/kb/platform/documents/{document_id}")
    assert response.status_code == 204
    assert service.await_args.args == (db,)
    assert service.await_args.kwargs["actor"] is actor
    assert service.await_args.kwargs["document_id"] == document_id
