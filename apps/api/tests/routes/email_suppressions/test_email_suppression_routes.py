# apps/api/tests/routes/email_suppressions/test_email_suppression_routes.py

"""Role gates on the Do Not Email list routes."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.audit_event import AuditEvent
from models.email_suppression import WorkspaceEmailSuppression
from models.workspace import Workspace, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio

URL = "/api/v1/email-suppressions/"


async def _member_headers(
    db: AsyncSession, workspace: Workspace, role: WorkspaceRole
) -> dict[str, str]:
    user = build_user(email=f"suppression-{uuid4().hex}@example.com")
    db.add(user)
    await db.flush()
    db.add(build_workspace_membership(workspace_id=workspace.id, user_id=user.id, role=role))
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return bearer_headers(session["session_token"])


async def test_editor_adds_but_only_a_manager_removes_and_read_only_cannot_list(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    workspace = build_workspace(slug=f"suppressions-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    editor = await _member_headers(db_session, workspace, WorkspaceRole.MEMBER)
    reader = await _member_headers(db_session, workspace, WorkspaceRole.READ_ONLY)
    admin = await _member_headers(db_session, workspace, WorkspaceRole.ADMIN)

    added = await db_async_client.post(
        URL,
        headers=editor,
        json={"addresses": ["dana@example.com"], "reason": "Asked not to be contacted"},
    )
    assert added.status_code == 200
    entry_id = added.json()["added"][0]["id"]

    assert (await db_async_client.get(URL, headers=reader)).status_code == 403
    assert (await db_async_client.delete(f"{URL}{entry_id}", headers=editor)).status_code == 403
    assert await db_session.get(WorkspaceEmailSuppression, entry_id) is not None

    assert (await db_async_client.delete(f"{URL}{entry_id}", headers=admin)).status_code == 204
    assert await db_session.get(WorkspaceEmailSuppression, entry_id) is None
    removal = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == AuditResourceType.EMAIL_SUPPRESSION.value,
            AuditEvent.resource_id == entry_id,
            AuditEvent.action == AuditAction.DELETE.value,
        )
    )
    assert removal is not None
    assert removal.details["email"] == "dana@example.com"
