# apps/api/tests/routes/skills/test_skill_document_routes.py

"""HTTP-boundary tests for workspace skill document routes."""

from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from tests.factories import (
    build_skill,
    build_user,
    build_workspace,
    build_workspace_membership,
)
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


async def _authenticated_workspace_with_skill(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    documentation_refs: dict[str, object] | None = None,
) -> tuple[User, Workspace, object, dict[str, str]]:
    user = build_user(email=f"skill-doc-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"skill-docs-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="research",
        documentation_refs=documentation_refs or {},
    )
    db.add_all([user, workspace, membership, skill])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return user, workspace, skill, bearer_headers(session["session_token"])


async def _put_document_upload(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    skill_id: UUID,
    document_name: str,
    filename: str,
    content: bytes,
    content_type: str = "text/markdown",
) -> dict[str, object]:
    upload_response = await client.post(
        f"/api/v1/skills/{skill_id}/documents/upload",
        headers=headers,
        json={
            "document_name": document_name,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
        },
    )
    assert upload_response.status_code == 200
    upload_grant = upload_response.json()

    put_response = await client.put(
        _relative_url(upload_grant["upload"]["url"]),
        content=content,
        headers=upload_grant["upload"]["headers"],
    )
    assert put_response.status_code == 204
    return upload_grant


async def _confirm_document_upload(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    skill_id: UUID,
    upload_token: str,
) -> dict[str, object]:
    confirm_response = await client.post(
        f"/api/v1/skills/{skill_id}/documents/confirm",
        headers=headers,
        json={"upload_token": upload_token},
    )
    assert confirm_response.status_code == 200
    return confirm_response.json()


async def _download_document_original(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    skill_id: UUID,
    document_name: str,
) -> tuple[bytes, dict[str, object]]:
    download_response = await client.get(
        f"/api/v1/skills/{skill_id}/documents/{document_name}/download",
        headers=headers,
    )
    assert download_response.status_code == 200
    download = download_response.json()

    object_response = await client.get(_relative_url(download["url"]))
    assert object_response.status_code == 200
    return object_response.content, download


async def test_skill_document_upload_confirm_read_download_and_delete(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    _user, _workspace, skill, headers = await _authenticated_workspace_with_skill(db_session)
    content = b"# Quick start\nFollow these steps."

    upload_grant = await _put_document_upload(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        document_name="quick_start",
        filename="Guide.md",
        content=content,
    )
    assert upload_grant["upload"]["ref"]["bucket"] == "private"

    confirmed = await _confirm_document_upload(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        upload_token=upload_grant["upload_token"],
    )
    assert confirmed["name"] == "quick_start"
    assert confirmed["status"] == "ready"
    assert confirmed["markdown"].endswith("/converted.md")
    assert confirmed["original"].endswith("/original/Guide.md")
    assert confirmed["filename"] == "Guide.md"

    list_response = await db_async_client.get(
        f"/api/v1/skills/{skill.id}/documents",
        headers=headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    markdown_response = await db_async_client.get(
        f"/api/v1/skills/{skill.id}/documents/quick_start/markdown",
        headers=headers,
    )
    assert markdown_response.status_code == 200
    assert markdown_response.json() == {
        "name": "quick_start",
        "content": content.decode(),
        "truncated": False,
    }

    download_response = await db_async_client.get(
        f"/api/v1/skills/{skill.id}/documents/quick_start/download",
        headers=headers,
    )
    assert download_response.status_code == 200
    download = download_response.json()
    assert download["method"] == "GET"
    assert download["ref"]["bucket"] == "private"
    assert 'filename="Guide.md"' in download["headers"]["content-disposition"]

    delete_response = await db_async_client.delete(
        f"/api/v1/skills/{skill.id}/documents/quick_start",
        headers=headers,
    )
    assert delete_response.status_code == 204

    empty_list_response = await db_async_client.get(
        f"/api/v1/skills/{skill.id}/documents",
        headers=headers,
    )
    assert empty_list_response.status_code == 200
    assert empty_list_response.json()["total"] == 0

    audit_events = (
        await db_session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.action == AuditAction.UPDATE.value,
                AuditEvent.resource_type == AuditResourceType.SKILL.value,
                AuditEvent.resource_id == str(skill.id),
            )
            .order_by(AuditEvent.created_at)
        )
    ).scalars().all()
    assert [event.details["action"] for event in audit_events] == ["upload", "delete"]


async def test_unconfirmed_replacement_upload_does_not_overwrite_current_original(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    _user, _workspace, skill, headers = await _authenticated_workspace_with_skill(db_session)
    original_content = b"# Original\nKeep this until confirm."
    replacement_content = b"# Replacement\nOnly visible after confirm."

    original_grant = await _put_document_upload(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        document_name="quick_start",
        filename="Original.md",
        content=original_content,
    )
    await _confirm_document_upload(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        upload_token=original_grant["upload_token"],
    )

    replacement_grant = await _put_document_upload(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        document_name="quick_start",
        filename="Replacement.md",
        content=replacement_content,
    )

    downloaded_before_confirm, current_download = await _download_document_original(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        document_name="quick_start",
    )
    assert downloaded_before_confirm == original_content
    assert 'filename="Original.md"' in current_download["headers"]["content-disposition"]

    replacement = await _confirm_document_upload(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        upload_token=replacement_grant["upload_token"],
    )
    assert replacement["filename"] == "Replacement.md"

    downloaded_after_confirm, replacement_download = await _download_document_original(
        db_async_client,
        headers=headers,
        skill_id=skill.id,
        document_name="quick_start",
    )
    assert downloaded_after_confirm == replacement_content
    assert 'filename="Replacement.md"' in replacement_download["headers"]["content-disposition"]


async def test_skill_document_confirm_rejects_token_for_different_skill(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    user, workspace, skill, headers = await _authenticated_workspace_with_skill(db_session)
    other_skill = build_skill(workspace=workspace, created_by=user, name="other")
    db_session.add(other_skill)
    await db_session.commit()

    upload_response = await db_async_client.post(
        f"/api/v1/skills/{skill.id}/documents/upload",
        headers=headers,
        json={
            "document_name": "quick_start",
            "filename": "guide.md",
            "content_type": "text/markdown",
            "size_bytes": 4,
        },
    )
    assert upload_response.status_code == 200

    confirm_response = await db_async_client.post(
        f"/api/v1/skills/{other_skill.id}/documents/confirm",
        headers=headers,
        json={"upload_token": upload_response.json()["upload_token"]},
    )

    assert confirm_response.status_code == 400
    assert confirm_response.json()["field"] == "upload_token"


async def test_skill_document_upload_rejects_new_document_over_cap(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAX_SKILL_DOCUMENTS_PER_SKILL", 1)
    _user, _workspace, skill, headers = await _authenticated_workspace_with_skill(
        db_session,
        documentation_refs={"existing_doc": {"status": "ready"}},
    )

    response = await db_async_client.post(
        f"/api/v1/skills/{skill.id}/documents/upload",
        headers=headers,
        json={
            "document_name": "new_doc",
            "filename": "guide.md",
            "content_type": "text/markdown",
            "size_bytes": 4,
        },
    )

    assert response.status_code == 400
    assert response.json()["field"] == "document_name"


async def test_skill_document_markdown_for_failed_entry_returns_not_found(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    local_storage_settings: None,
) -> None:
    _user, _workspace, skill, headers = await _authenticated_workspace_with_skill(
        db_session,
        documentation_refs={
            "bad_doc": {
                "original": "workspaces/w/skills/s/docs/bad_doc/original.pdf",
                "markdown": None,
                "filename": "bad_doc.pdf",
                "content_type": "application/pdf",
                "size_bytes": 10,
                "markdown_size_bytes": None,
                "status": "failed",
                "error": "Document could not be converted to markdown",
                "updated_at": datetime.now(UTC).isoformat(),
            }
        },
    )

    response = await db_async_client.get(
        f"/api/v1/skills/{skill.id}/documents/bad_doc/markdown",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["resource_type"] == "skill_document"
