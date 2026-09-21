"""Regression tests for replacing expired workspace invitations."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.audit_event import AuditEvent
from models.security import SecurityEvent
from models.workspace import WorkspaceInvitation, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.security import SecurityEventType
from services.workspaces.invitations import (
    accept_invitation_by_token,
    create_invitation,
    list_invitations,
)
from services.workspaces.schemas import WorkspaceInvitationCreateRequest
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request


@pytest.mark.parametrize("registered", [False, True])
async def test_expired_invitation_can_be_replaced(
    db_session: AsyncSession, registered: bool
) -> None:
    owner = build_user(email="alex@example.com")
    invited = build_user(email="dana@example.com")
    workspace = build_workspace()
    membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER
    )
    old_token = "expired-invitation-token"
    expired = WorkspaceInvitation(
        workspace_id=workspace.id,
        email="Dana@Example.com",
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(old_token),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    unrelated = WorkspaceInvitation(
        workspace_id=workspace.id,
        email="kai@example.com",
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("unrelated-expired-token"),
        expires_at=expired.expires_at,
    )
    db_session.add_all([owner, workspace, membership, expired, unrelated])
    if registered:
        db_session.add(invited)
    await db_session.flush()

    pending = await list_invitations(
        db_session,
        actor=owner,
        workspace_id=workspace.id,
        include_accepted=False,
        include_expired=False,
        limit=100,
        offset=0,
    )
    assert pending.total == 0

    created = await create_invitation(
        db_session,
        request=build_test_request(path=f"/api/v1/workspaces/{workspace.id}/invitations"),
        actor=owner,
        workspace_id=workspace.id,
        payload=WorkspaceInvitationCreateRequest(
            email=" DANA@example.com ",
            role=WorkspaceRole.MEMBER,
            expires_in_days=3,
        ),
    )

    assert expired.deleted is True
    assert expired.deleted_by == owner.id
    assert expired.accepted_at is None
    assert unrelated.deleted is False
    assert created.invitation.id != expired.id
    assert created.invitation.role == WorkspaceRole.MEMBER
    assert created.invitation.expires_at > datetime.now(UTC) + timedelta(days=2)
    assert created.token != old_token

    pending = await list_invitations(
        db_session,
        actor=owner,
        workspace_id=workspace.id,
        include_accepted=False,
        include_expired=False,
        limit=100,
        offset=0,
    )
    assert [invitation.id for invitation in pending.invitations] == [created.invitation.id]

    audit_events = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.workspace_id == workspace.id,
                AuditEvent.resource_type == AuditResourceType.INVITATION.value,
            )
        )
    ).all()
    assert {(event.action, event.resource_id) for event in audit_events} == {
        (AuditAction.DELETE.value, str(expired.id)),
        (AuditAction.CREATE.value, str(created.invitation.id)),
    }
    security_events = (
        await db_session.scalars(
            select(SecurityEvent).where(SecurityEvent.user_email == owner.email)
        )
    ).all()
    assert {event.event_type for event in security_events} == {
        SecurityEventType.WORKSPACE_INVITATION_DELETED.value,
        SecurityEventType.WORKSPACE_INVITATION_CREATED.value,
    }

    if not registered:
        db_session.add(invited)
        await db_session.flush()
    with pytest.raises(AppValidationError, match="Invalid or expired invitation link"):
        await accept_invitation_by_token(db_session, actor=invited, token=old_token)
    accepted = await accept_invitation_by_token(
        db_session,
        actor=invited,
        token=created.token,
    )
    assert accepted.status == "accepted"


@pytest.mark.parametrize("state", ["active", "accepted", "deleted"])
async def test_existing_invitation_state_is_preserved(db_session: AsyncSession, state: str) -> None:
    owner = build_user(email="alex@example.com")
    workspace = build_workspace()
    membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER
    )
    now = datetime.now(UTC)
    existing = WorkspaceInvitation(
        workspace_id=workspace.id,
        email="dana@example.com",
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("existing-token"),
        expires_at=now + timedelta(days=1) if state == "active" else now - timedelta(days=1),
        accepted_at=now if state == "accepted" else None,
        deleted=state == "deleted",
    )
    db_session.add_all([owner, workspace, membership, existing])
    await db_session.flush()
    existing_id = existing.id

    async def create():
        return await create_invitation(
            db_session,
            request=build_test_request(path=f"/api/v1/workspaces/{workspace.id}/invitations"),
            actor=owner,
            workspace_id=workspace.id,
            payload=WorkspaceInvitationCreateRequest(email=existing.email),
        )

    if state == "active":
        with pytest.raises(ConflictError, match="A pending invitation already exists"):
            async with db_session.begin_nested():
                await create()
    else:
        created = await create()
        assert created.invitation.id != existing_id

    await db_session.refresh(existing)
    assert existing.deleted is (state == "deleted")
    assert existing.accepted_at == (now if state == "accepted" else None)
    assert existing.verify_raw_token("existing-token")
