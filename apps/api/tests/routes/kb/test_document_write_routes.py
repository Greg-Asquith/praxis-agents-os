# apps/api/tests/routes/kb/test_document_write_routes.py

"""HTTP-boundary tests for knowledge-document management."""

from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.audit_event import AuditEvent
from models.workspace import WorkspaceRole
from tests.factories import (
    build_kb_document,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.auth import bearer_headers


async def _workspace_session(
    db: AsyncSession,
    *,
    role: WorkspaceRole,
):
    suffix = uuid4().hex
    user = build_user(email=f"kb-write-{suffix}@example.com")
    workspace = build_workspace(slug=f"kb-write-{suffix[:12]}")
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
    headers = {
        **bearer_headers(session["session_token"]),
        "X-Workspace": workspace.slug,
    }
    return user, workspace, headers


async def test_member_can_manage_documents_and_mutations_are_audited(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    created = await db_async_client.post(
        "/api/v1/kb/documents",
        headers=headers,
        json={
            "title": "Operator handbook",
            "content_md": "Workspace operations knowledge.",
            "is_private": False,
        },
    )
    assert created.status_code == 201
    document_id = created.json()["id"]

    listed = await db_async_client.get("/api/v1/kb/documents", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["documents"]] == [document_id]

    updated = await db_async_client.patch(
        f"/api/v1/kb/documents/{document_id}",
        headers=headers,
        json={"title": "Updated handbook", "is_private": True},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated handbook"
    assert updated.json()["is_private"] is True

    deleted = await db_async_client.delete(
        f"/api/v1/kb/documents/{document_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    audits = (
        await db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.workspace_id == workspace.id,
                AuditEvent.resource_type == "kb_document",
                AuditEvent.resource_id == document_id,
            )
            .order_by(AuditEvent.occurred_at)
        )
    ).all()
    assert [event.action for event in audits] == ["create", "update", "delete"]


async def test_read_only_cannot_create_documents(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.READ_ONLY,
    )
    response = await db_async_client.post(
        "/api/v1/kb/documents",
        headers=headers,
        json={"title": "Denied", "content_md": "No write access."},
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_cross_workspace_document_mutations_return_not_found(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _workspace_session(
        db_session,
        role=WorkspaceRole.MEMBER,
    )
    other_workspace = build_workspace(slug=f"kb-other-{uuid4().hex[:10]}")
    db_session.add(other_workspace)
    await db_session.flush()
    other_membership = build_workspace_membership(
        workspace_id=other_workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    hidden = build_kb_document(
        workspace=other_workspace,
        created_by_user_id=user.id,
    )
    db_session.add_all([other_membership, hidden])
    await db_session.commit()

    response = await db_async_client.patch(
        f"/api/v1/kb/documents/{hidden.id}",
        headers=headers,
        json={"title": "Cross-tenant update"},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert workspace.id != other_workspace.id
