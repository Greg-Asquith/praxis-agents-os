"""HTTP-boundary tests for workspace file routes."""

from collections.abc import Iterator
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from httpx import AsyncClient
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


def _relative_url(absolute_url: str) -> str:
    parsed = urlsplit(absolute_url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.MEMBER,
) -> dict[str, str]:
    user = build_user(email=f"file-route-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"file-routes-{uuid4().hex[:8]}")
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
    return bearer_headers(session["session_token"])


async def _upload_and_confirm_file(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    filename: str = "notes.txt",
    content: bytes = b"hello",
) -> dict[str, object]:
    upload_response = await client.post(
        "/api/v1/files/uploads",
        headers=headers,
        json={
            "filename": filename,
            "content_type": "text/plain",
            "size_bytes": len(content),
        },
    )
    assert upload_response.status_code == 200
    grant = upload_response.json()["grant"]
    put_response = await client.put(
        _relative_url(grant["upload"]["url"]),
        content=content,
        headers=grant["upload"]["headers"],
    )
    assert put_response.status_code == 204
    confirm_response = await client.post(
        "/api/v1/files/uploads/confirm",
        headers=headers,
        json={"upload_token": grant["upload_token"]},
    )
    assert confirm_response.status_code == 200
    return confirm_response.json()


async def test_file_routes_upload_list_download_edit_conflict_and_delete(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers = await _authenticated_workspace(db_session)
    confirmed = await _upload_and_confirm_file(db_async_client, headers=headers)

    list_response = await db_async_client.get("/api/v1/files/", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    usage_response = await db_async_client.get("/api/v1/files/usage", headers=headers)
    assert usage_response.status_code == 200
    assert usage_response.json()["used_bytes"] == len(b"hello")

    download_response = await db_async_client.post(
        f"/api/v1/files/{confirmed['id']}/download",
        headers=headers,
        json={},
    )
    assert download_response.status_code == 200
    object_response = await db_async_client.get(_relative_url(download_response.json()["download"]["url"]))
    assert object_response.status_code == 200
    assert object_response.content == b"hello"

    conflict_response = await db_async_client.put(
        f"/api/v1/files/{confirmed['id']}/content",
        headers=headers,
        json={"content": "new", "expected_current_revision_id": str(uuid4())},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.headers["content-type"].startswith("application/problem+json")
    assert conflict_response.json()["current_revision_id"] == confirmed["current_revision_id"]

    edit_response = await db_async_client.put(
        f"/api/v1/files/{confirmed['id']}/content",
        headers=headers,
        json={
            "content": "new",
            "expected_current_revision_id": confirmed["current_revision_id"],
        },
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["revision_count"] == 2

    delete_response = await db_async_client.delete(
        f"/api/v1/files/{confirmed['id']}",
        headers=headers,
    )
    assert delete_response.status_code == 204


async def test_file_routes_reject_read_only_upload(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers = await _authenticated_workspace(db_session, role=WorkspaceRole.READ_ONLY)

    response = await db_async_client.post(
        "/api/v1/files/uploads",
        headers=headers,
        json={
            "filename": "blocked.txt",
            "content_type": "text/plain",
            "size_bytes": 5,
        },
    )

    assert response.status_code == 403
