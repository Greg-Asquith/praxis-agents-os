"""User audit events retain their explicit global or workspace scope."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import get_maintenance_async_db_session_factory, set_session_tenant_context
from models.audit_event import AuditEvent
from services.audit_events import AuditAction, record_user_audit_event
from tests.factories import build_user, build_workspace, build_workspace_membership


async def test_global_user_audit_does_not_inherit_default_workspace(
    db_session: AsyncSession,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = build_user(email="global-audit@example.com")
    workspace = build_workspace(slug="global-audit")
    user.default_workspace_id = workspace.id
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
    )
    db_session.add_all([user, workspace, membership])
    await db_session.flush()

    await record_user_audit_event(
        db_session,
        action=AuditAction.UPDATE,
        user=user,
        actor=user,
        request=Request(
            {
                "type": "http",
                "method": "PATCH",
                "path": "/me",
                "headers": [],
                "client": ("127.0.0.1", 1234),
            }
        ),
        details={"field": "password"},
    )

    async with db_session_factory() as runtime_db:
        await set_session_tenant_context(
            runtime_db,
            workspace_id=workspace.id,
            user_id=user.id,
        )
        assert (
            await runtime_db.scalar(
                select(AuditEvent).where(AuditEvent.resource_id == str(user.id))
            )
            is None
        )
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        event = await maintenance_db.scalar(
            select(AuditEvent).where(AuditEvent.resource_id == str(user.id))
        )
        assert event is not None
        assert event.workspace_id is None
        assert event.details == {"field": "password"}
