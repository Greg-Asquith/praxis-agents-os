# apps/api/tests/services/users/test_user_management_services.py

"""Focused tests for high-risk user-management service behavior."""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.exceptions.general import AppValidationError
from models.audit_event import AuditEvent
from models.session import Session
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.users import create_user, delete_user, update_user
from services.users.schemas import UserCreateRequest, UserUpdateRequest
from tests.factories import build_user
from tests.support.requests import build_test_request

pytestmark = pytest.mark.asyncio


async def test_create_user_provisions_personal_workspace_and_records_audit(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="admin@example.com", display_name="Admin")
    strong_password = "Password123"
    db_session.add(actor)
    await db_session.flush()

    result = await create_user(
        db_session,
        request=build_test_request(path="/api/v1/users/"),
        actor=actor,
        payload=UserCreateRequest(
            email=" New.User@Example.COM ",
            display_name=" New User ",
            password=strong_password,
        ),
    )

    user = await db_session.get(User, result.id)
    assert user is not None
    assert result.email == "new.user@example.com"
    assert result.display_name == "New User"
    assert user.verify_password(strong_password)
    assert user.default_workspace_id is not None

    workspace = await db_session.get(Workspace, user.default_workspace_id)
    assert workspace is not None
    assert workspace.is_personal is True
    assert workspace.name == "My Workspace"

    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.OWNER.value

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.CREATE.value,
            AuditEvent.resource_type == AuditResourceType.USER.value,
            AuditEvent.resource_id == str(user.id),
        )
    )
    assert audit_event is not None
    assert audit_event.workspace_id == workspace.id
    assert audit_event.actor_user_id == actor.id
    assert audit_event.details["source"] == "admin"


async def test_update_user_deactivation_revokes_existing_sessions_and_audits(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="admin@example.com")
    target = build_user(email="target@example.com")
    db_session.add_all([actor, target])
    await db_session.flush()

    session_result = await session_manager.create_session(db_session, str(target.id))

    result = await update_user(
        db_session,
        request=build_test_request(path=f"/api/v1/users/{target.id}", method="PATCH"),
        actor=actor,
        user_id=target.id,
        payload=UserUpdateRequest(is_active=False),
    )

    session = await db_session.get(Session, UUID(session_result["session_id"]))
    assert result.is_active is False
    assert target.is_active is False
    assert session is not None
    assert session.deleted is True

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.UPDATE.value,
            AuditEvent.resource_type == AuditResourceType.USER.value,
            AuditEvent.resource_id == str(target.id),
        )
    )
    assert audit_event is not None
    assert audit_event.details == {"fields": ["is_active"], "revoked_sessions": 1}


async def test_delete_user_rejects_self_deletion(db_session: AsyncSession) -> None:
    actor = build_user(email="admin@example.com")
    db_session.add(actor)
    await db_session.flush()

    with pytest.raises(AppValidationError, match="cannot delete your own user account"):
        await delete_user(
            db_session,
            request=build_test_request(path=f"/api/v1/users/{actor.id}", method="DELETE"),
            actor=actor,
            user_id=actor.id,
        )

    assert actor.deleted is False
    assert actor.is_active is True
