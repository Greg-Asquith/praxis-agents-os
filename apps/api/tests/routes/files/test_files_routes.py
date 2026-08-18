"""HTTP-boundary tests for workspace file routes."""

from collections.abc import Iterator
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from models.audit_event import AuditEvent
from models.files import File, FileFolder
from models.workspace import WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.files import delete_folder as delete_folder_service
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
    content_type: str = "text/plain",
    content: bytes = b"hello",
    folder_id: str | None = None,
) -> dict[str, object]:
    upload_response = await client.post(
        "/api/v1/files/uploads",
        headers=headers,
        json={
            "filename": filename,
            "content_type": content_type,
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
        json={"upload_token": grant["upload_token"], "folder_id": folder_id},
    )
    assert confirm_response.status_code == 200
    return confirm_response.json()


async def test_file_folder_routes_scope_move_upload_and_delete_contents(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await _authenticated_workspace(db_session)
    created = await db_async_client.post(
        "/api/v1/files/folders",
        headers=headers,
        json={"name": " Campaign Outputs ", "description": "Working files"},
    )
    assert created.status_code == 200
    folder = created.json()
    assert folder["name"] == "Campaign Outputs"

    collision = await db_async_client.post(
        "/api/v1/files/folders",
        headers=headers,
        json={"name": "campaign outputs"},
    )
    assert collision.status_code == 200
    assert collision.json()["name"] == "campaign outputs (2)"

    renamed = await db_async_client.patch(
        f"/api/v1/files/folders/{folder['id']}",
        headers=headers,
        json={"name": "Campaign Deliverables", "description": "Final working files"},
    )
    assert renamed.status_code == 200
    folder = renamed.json()

    in_folder = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        filename="deck.pptx",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        content=b"deck",
        folder_id=folder["id"],
    )
    at_root = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        filename="notes.txt",
    )
    assert in_folder["folder_id"] == folder["id"]
    assert in_folder["folder_name"] == "Campaign Deliverables"

    folders_response = await db_async_client.get("/api/v1/files/folders", headers=headers)
    listed = {item["id"]: item for item in folders_response.json()["folders"]}
    assert listed[folder["id"]]["file_count"] == 1
    assert listed[folder["id"]]["total_bytes"] == 4
    assert listed[folder["id"]]["updated_at"] == in_folder["updated_at"]

    root_response = await db_async_client.get(
        "/api/v1/files/", headers=headers, params={"root_only": "true"}
    )
    assert [item["id"] for item in root_response.json()["files"]] == [at_root["id"]]
    scoped_response = await db_async_client.get(
        "/api/v1/files/", headers=headers, params={"folder_id": folder["id"]}
    )
    assert [item["id"] for item in scoped_response.json()["files"]] == [in_folder["id"]]

    moved = await db_async_client.post(
        "/api/v1/files/move",
        headers=headers,
        json={"file_ids": [at_root["id"]], "folder_id": folder["id"]},
    )
    assert moved.status_code == 200
    assert moved.json()["files"][0]["folder_name"] == "Campaign Deliverables"

    move_audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == AuditResourceType.FILE.value,
            AuditEvent.resource_id == at_root["id"],
            AuditEvent.action == AuditAction.UPDATE.value,
            AuditEvent.details["action"].astext == "move",
        )
    )
    assert move_audit is not None
    assert move_audit.details["to_folder_id"] == folder["id"]

    moved_to_root = await db_async_client.patch(
        f"/api/v1/files/{at_root['id']}",
        headers=headers,
        json={"folder_id": None},
    )
    assert moved_to_root.status_code == 200
    assert moved_to_root.json()["folder_id"] is None

    missing_file_move = await db_async_client.post(
        "/api/v1/files/move",
        headers=headers,
        json={"file_ids": [str(uuid4())], "folder_id": folder["id"]},
    )
    assert missing_file_move.status_code == 400

    other_headers = await _authenticated_workspace(db_session)
    other_folder = await db_async_client.post(
        "/api/v1/files/folders",
        headers=other_headers,
        json={"name": "Other workspace"},
    )
    cross_workspace_move = await db_async_client.post(
        "/api/v1/files/move",
        headers=headers,
        json={"file_ids": [at_root["id"]], "folder_id": other_folder.json()["id"]},
    )
    assert cross_workspace_move.status_code == 404

    disposable_folder = await db_async_client.post(
        "/api/v1/files/folders",
        headers=headers,
        json={"name": "Disposable"},
    )
    disposable_file = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        filename="disposable.txt",
        folder_id=disposable_folder.json()["id"],
    )
    await db_session.execute(
        delete(FileFolder).where(FileFolder.id == UUID(disposable_folder.json()["id"]))
    )
    await db_session.flush()
    persisted_disposable = await db_session.get(File, UUID(disposable_file["id"]))
    assert persisted_disposable is not None
    await db_session.refresh(persisted_disposable)
    assert persisted_disposable.folder_id is None

    delete_module = __import__(delete_folder_service.__module__, fromlist=["delete_folder"])
    with monkeypatch.context() as patcher:
        patcher.setattr(delete_module, "MAX_FOLDER_DELETE_AUDIT_FILE_IDS", 0)
        delete_response = await db_async_client.delete(
            f"/api/v1/files/folders/{folder['id']}", headers=headers
        )
    assert delete_response.status_code == 204
    assert (
        await db_async_client.get(f"/api/v1/files/{in_folder['id']}", headers=headers)
    ).status_code == 404

    folder_audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == AuditResourceType.FILE_FOLDER.value,
            AuditEvent.resource_id == folder["id"],
            AuditEvent.action == AuditAction.DELETE.value,
        )
    )
    assert folder_audit is not None
    assert folder_audit.details["file_count"] == 1
    assert folder_audit.details["file_ids"] == []
    assert folder_audit.details["file_ids_truncated"] is True
    rename_audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == AuditResourceType.FILE_FOLDER.value,
            AuditEvent.resource_id == folder["id"],
            AuditEvent.action == AuditAction.UPDATE.value,
        )
    )
    assert rename_audit is not None


async def test_folder_delete_rejects_more_than_the_synchronous_limit(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = await _authenticated_workspace(db_session)
    folder = await db_async_client.post(
        "/api/v1/files/folders",
        headers=headers,
        json={"name": "Too large"},
    )
    file = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        folder_id=folder.json()["id"],
    )
    delete_module = __import__(delete_folder_service.__module__, fromlist=["delete_folder"])
    monkeypatch.setattr(delete_module, "MAX_SYNCHRONOUS_FOLDER_DELETE_FILES", 0)

    response = await db_async_client.delete(
        f"/api/v1/files/folders/{folder.json()['id']}",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["max_file_count"] == 0
    assert (
        await db_async_client.get(f"/api/v1/files/{file['id']}", headers=headers)
    ).status_code == 200


async def test_file_routes_list_supports_sorting_and_pagination(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers = await _authenticated_workspace(db_session)
    for filename, content in (
        ("zeta.txt", b"z"),
        ("alpha.txt", b"aa"),
        ("middle.txt", b"mmm"),
    ):
        await _upload_and_confirm_file(
            db_async_client,
            headers=headers,
            filename=filename,
            content=content,
        )

    name_response = await db_async_client.get(
        "/api/v1/files/",
        headers=headers,
        params={
            "limit": 2,
            "offset": 1,
            "sort_by": "name",
            "sort_direction": "asc",
        },
    )
    assert name_response.status_code == 200
    assert name_response.json()["total"] == 3
    assert [file["name"] for file in name_response.json()["files"]] == [
        "middle.txt",
        "zeta.txt",
    ]

    size_response = await db_async_client.get(
        "/api/v1/files/",
        headers=headers,
        params={"sort_by": "size_bytes", "sort_direction": "desc"},
    )
    assert size_response.status_code == 200
    assert [file["name"] for file in size_response.json()["files"]] == [
        "middle.txt",
        "alpha.txt",
        "zeta.txt",
    ]


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ({"sort_by": "content_hash"}, "sort_by"),
        ({"sort_direction": "down"}, "sort_direction"),
    ],
)
async def test_file_routes_list_rejects_unknown_sort_options(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    query: dict[str, str],
    field: str,
) -> None:
    headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get("/api/v1/files/", headers=headers, params=query)

    assert response.status_code == 400
    assert response.json()["field"] == field


async def test_file_routes_read_revision_content_for_editable_revisions(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers = await _authenticated_workspace(db_session)
    confirmed = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        content=b"first",
    )
    original_revision_id = str(confirmed["current_revision_id"])

    original_response = await db_async_client.get(
        f"/api/v1/files/{confirmed['id']}/revisions/{original_revision_id}/content",
        headers=headers,
    )
    assert original_response.status_code == 200
    original_content = original_response.json()
    assert original_content["content"] == "first"
    assert original_content["revision_id"] == original_revision_id
    assert original_content["content_type"] == "text/plain"

    read_audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.READ.value,
            AuditEvent.resource_type == AuditResourceType.FILE.value,
            AuditEvent.resource_id == str(confirmed["id"]),
        )
    )
    assert read_audit is not None
    assert read_audit.details["revision_id"] == original_revision_id
    assert read_audit.details["source"] == "content"

    edit_response = await db_async_client.put(
        f"/api/v1/files/{confirmed['id']}/content",
        headers=headers,
        json={
            "content": "second",
            "expected_current_revision_id": original_revision_id,
        },
    )
    assert edit_response.status_code == 200
    edited_revision_id = edit_response.json()["current_revision_id"]

    reread_original_response = await db_async_client.get(
        f"/api/v1/files/{confirmed['id']}/revisions/{original_revision_id}/content",
        headers=headers,
    )
    assert reread_original_response.status_code == 200
    assert reread_original_response.json()["content"] == "first"

    edited_response = await db_async_client.get(
        f"/api/v1/files/{confirmed['id']}/revisions/{edited_revision_id}/content",
        headers=headers,
    )
    assert edited_response.status_code == 200
    assert edited_response.json()["content"] == "second"


async def test_file_routes_reject_revision_content_for_non_editable_revisions(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    headers = await _authenticated_workspace(db_session)
    confirmed = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        filename="report.pdf",
        content_type="application/pdf",
        content=b"%PDF",
    )

    response = await db_async_client.get(
        f"/api/v1/files/{confirmed['id']}/revisions/{confirmed['current_revision_id']}/content",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["field"] == "revision_id"
    assert response.json()["content_type"] == "application/pdf"


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("screen.png", "image/png", b"png"),
        ("clip.mp4", "video/mp4", b"video"),
        ("report.pdf", "application/pdf", b"%PDF"),
    ],
)
async def test_file_preview_route_returns_inline_media_url_without_read_audit(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    filename: str,
    content_type: str,
    content: bytes,
) -> None:
    headers = await _authenticated_workspace(db_session)
    confirmed = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        filename=filename,
        content_type=content_type,
        content=content,
    )

    preview_response = await db_async_client.post(
        f"/api/v1/files/{confirmed['id']}/preview",
        headers=headers,
    )

    assert preview_response.status_code == 200
    assert "download=1" not in preview_response.json()["preview"]["url"]
    object_response = await db_async_client.get(
        _relative_url(preview_response.json()["preview"]["url"])
    )
    assert object_response.status_code == 200
    assert object_response.content == content
    assert object_response.headers["content-type"] == content_type
    assert "content-disposition" not in object_response.headers
    if content_type == "video/mp4":
        range_response = await db_async_client.get(
            _relative_url(preview_response.json()["preview"]["url"]),
            headers={"range": "bytes=0-1"},
        )
        assert range_response.status_code == 206
        assert range_response.content == content[:2]
        assert range_response.headers["content-range"] == f"bytes 0-1/{len(content)}"
    read_audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.READ.value,
            AuditEvent.resource_type == AuditResourceType.FILE.value,
            AuditEvent.resource_id == str(confirmed["id"]),
        )
    )
    assert read_audit is None

    document = await _upload_and_confirm_file(
        db_async_client,
        headers=headers,
        filename="brief.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"docx",
    )
    document_preview_response = await db_async_client.post(
        f"/api/v1/files/{document['id']}/preview",
        headers=headers,
    )
    assert document_preview_response.status_code == 400
    assert document_preview_response.headers["content-type"].startswith("application/problem+json")
    assert document_preview_response.json()["field"] == "file_id"


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

    update_response = await db_async_client.patch(
        f"/api/v1/files/{confirmed['id']}",
        headers=headers,
        json={"description": None, "name": "renamed notes.txt"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "renamed notes.txt"

    download_response = await db_async_client.post(
        f"/api/v1/files/{confirmed['id']}/download",
        headers=headers,
        json={},
    )
    assert download_response.status_code == 200
    assert "download=1" in download_response.json()["download"]["url"]
    object_response = await db_async_client.get(
        _relative_url(download_response.json()["download"]["url"])
    )
    assert object_response.status_code == 200
    assert object_response.content == b"hello"
    assert object_response.headers["content-disposition"] == (
        'attachment; filename="renamed notes.txt"'
    )
    read_audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.READ.value,
            AuditEvent.resource_type == AuditResourceType.FILE.value,
            AuditEvent.resource_id == str(confirmed["id"]),
        )
    )
    assert read_audit is not None

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
