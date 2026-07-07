# apps/api/tests/services/workspaces/test_workspace_management_services.py

"""Focused tests for workspace-management service invariants."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError
from models.audit_event import AuditEvent
from models.security import SecurityEvent
from models.workspace import WorkspaceInvitation, WorkspaceMembership, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.security import SecurityEventType
from services.workspaces import create_workspace, delete_workspace
from services.workspaces.invitations import (
    accept_invitation_by_token,
    accept_pending_invitations_for_user,
)
from services.workspaces.memberships import delete_membership, update_membership
from services.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceMembershipUpdateRequest,
)
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request

pytestmark = pytest.mark.asyncio


async def test_create_workspace_generates_unique_slug_and_owner_membership(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="owner@example.com")
    existing_workspace = build_workspace(slug="agent-team", name="Existing Agent Team")
    db_session.add_all([actor, existing_workspace])
    await db_session.flush()

    result = await create_workspace(
        db_session,
        request=build_test_request(path="/api/v1/workspaces/"),
        actor=actor,
        payload=WorkspaceCreateRequest(name="Agent Team"),
    )

    assert result.slug == "agent-team-2"
    assert result.current_user_role == WorkspaceRole.OWNER

    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == result.id,
            WorkspaceMembership.user_id == actor.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.OWNER.value

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.CREATE.value,
            AuditEvent.resource_type == AuditResourceType.WORKSPACE.value,
            AuditEvent.resource_id == str(result.id),
        )
    )
    assert audit_event is not None
    assert audit_event.details["slug"] == "agent-team-2"
    assert audit_event.details["owner_membership_id"] == str(membership.id)


async def test_delete_workspace_rejects_personal_workspaces(db_session: AsyncSession) -> None:
    actor = build_user(email="owner@example.com")
    workspace = build_workspace(slug="personal-owner", is_personal=True)
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add_all([actor, workspace, membership])
    await db_session.flush()

    with pytest.raises(AppValidationError, match="Personal workspaces cannot be deleted"):
        await delete_workspace(
            db_session,
            request=build_test_request(
                path=f"/api/v1/workspaces/{workspace.id}",
                method="DELETE",
            ),
            actor=actor,
            workspace_id=workspace.id,
        )

    assert workspace.deleted is False
    assert membership.deleted is False


async def test_delete_workspace_soft_deletes_children_and_clears_user_defaults(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="owner@example.com")
    member = build_user(email="member@example.com")
    workspace = build_workspace(slug="team-workspace", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.OWNER,
    )
    member_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=member.id,
        role=WorkspaceRole.MEMBER,
    )
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email="invited@example.com",
        role=WorkspaceRole.MEMBER.value,
        invited_by=actor.id,
        token_hash=WorkspaceInvitation.hash_raw_token("raw-invite-token"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    member.default_workspace_id = workspace.id
    db_session.add_all([actor, member, workspace, owner_membership, member_membership, invitation])
    await db_session.flush()

    await delete_workspace(
        db_session,
        request=build_test_request(
            path=f"/api/v1/workspaces/{workspace.id}",
            method="DELETE",
        ),
        actor=actor,
        workspace_id=workspace.id,
    )
    await db_session.refresh(member)

    assert workspace.deleted is True
    assert owner_membership.deleted is True
    assert member_membership.deleted is True
    assert invitation.deleted is True
    assert member.default_workspace_id is None


async def test_update_membership_rejects_demoting_the_last_owner(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="owner@example.com")
    workspace = build_workspace(slug="team-workspace", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add_all([actor, workspace, owner_membership])
    await db_session.flush()

    with pytest.raises(AppValidationError, match="must keep at least one active owner"):
        await update_membership(
            db_session,
            request=build_test_request(
                path=f"/api/v1/workspaces/{workspace.id}/memberships/{owner_membership.id}",
                method="PATCH",
            ),
            actor=actor,
            workspace_id=workspace.id,
            membership_id=owner_membership.id,
            payload=WorkspaceMembershipUpdateRequest(role=WorkspaceRole.MEMBER),
        )

    assert owner_membership.role == WorkspaceRole.OWNER.value


async def test_delete_membership_rejects_non_manager_removing_another_member(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="member-one@example.com")
    target = build_user(email="member-two@example.com")
    owner = build_user(email="owner@example.com")
    workspace = build_workspace(slug="team-workspace", is_personal=False)
    actor_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.MEMBER,
    )
    target_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=target.id,
        role=WorkspaceRole.MEMBER,
    )
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add_all(
        [
            actor,
            target,
            owner,
            workspace,
            actor_membership,
            target_membership,
            owner_membership,
        ]
    )
    await db_session.flush()

    with pytest.raises(AuthorizationError, match="Requires higher level role"):
        await delete_membership(
            db_session,
            request=build_test_request(
                path=f"/api/v1/workspaces/{workspace.id}/memberships/{target_membership.id}",
                method="DELETE",
            ),
            actor=actor,
            workspace_id=workspace.id,
            membership_id=target_membership.id,
        )

    assert target_membership.deleted is False


async def test_accept_invitation_by_token_creates_membership_and_records_security_event(
    db_session: AsyncSession,
) -> None:
    owner = build_user(email="owner@example.com")
    invited = build_user(email="invited@example.com")
    workspace = build_workspace(slug="team-workspace", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )
    raw_token = "raw-invite-token-12345"
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited.email,
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, invited, workspace, owner_membership, invitation])
    await db_session.flush()

    response = await accept_invitation_by_token(
        db_session,
        request=build_test_request(path="/api/v1/workspaces/invitations/accept"),
        actor=invited,
        token=raw_token,
    )

    assert response.status == "accepted"
    assert response.membership.user_id == invited.id
    assert response.membership.role == WorkspaceRole.ADMIN
    assert invitation.accepted_at is not None

    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == invited.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.ADMIN.value

    security_event = await db_session.scalar(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.WORKSPACE_INVITATION_ACCEPTED.value,
            SecurityEvent.user_email == invited.email,
        )
    )
    assert security_event is not None
    assert security_event.details["invitation_id"] == str(invitation.id)
    assert security_event.details["membership_id"] == str(membership.id)


async def test_accept_pending_invitations_for_user_accepts_valid_matches_only_and_skips_failures(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = build_user(email="owner@example.com")
    invited = build_user(email="invited@example.com")
    valid_workspace = build_workspace(slug="valid-team", is_personal=False)
    failing_workspace = build_workspace(slug="failing-team", is_personal=False)
    expired_workspace = build_workspace(slug="expired-team", is_personal=False)
    other_workspace = build_workspace(slug="other-team", is_personal=False)
    owner_memberships = [
        build_workspace_membership(
            workspace_id=workspace.id,
            user_id=owner.id,
            role=WorkspaceRole.OWNER,
        )
        for workspace in [valid_workspace, failing_workspace, expired_workspace, other_workspace]
    ]
    valid_invitation = WorkspaceInvitation(
        workspace_id=valid_workspace.id,
        email=invited.email,
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("valid-invite-token"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    failing_invitation = WorkspaceInvitation(
        workspace_id=failing_workspace.id,
        email=invited.email,
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("failing-invite-token"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    expired_invitation = WorkspaceInvitation(
        workspace_id=expired_workspace.id,
        email=invited.email,
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("expired-invite-token"),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    other_invitation = WorkspaceInvitation(
        workspace_id=other_workspace.id,
        email="someone-else@example.com",
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("other-invite-token"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all(
        [
            owner,
            invited,
            valid_workspace,
            failing_workspace,
            expired_workspace,
            other_workspace,
            *owner_memberships,
            valid_invitation,
            failing_invitation,
            expired_invitation,
            other_invitation,
        ]
    )
    await db_session.flush()

    pending_module = importlib.import_module(
        "services.workspaces.invitations.accept_pending_invitations_for_user"
    )
    original_accept_invitation = pending_module.accept_invitation

    async def fake_accept_invitation(*args, **kwargs):
        if kwargs["invitation"].id == failing_invitation.id:
            raise RuntimeError("simulated invite failure")
        return await original_accept_invitation(*args, **kwargs)

    monkeypatch.setattr(pending_module, "accept_invitation", fake_accept_invitation)

    accepted_count = await accept_pending_invitations_for_user(
        db_session,
        user=invited,
        request=build_test_request(path="/api/v1/auth/login"),
    )

    assert accepted_count == 1
    assert valid_invitation.accepted_at is not None
    assert failing_invitation.accepted_at is None
    assert expired_invitation.accepted_at is None
    assert other_invitation.accepted_at is None

    accepted_membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == valid_workspace.id,
            WorkspaceMembership.user_id == invited.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert accepted_membership is not None
    assert accepted_membership.role == WorkspaceRole.MEMBER.value

    skipped_membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == failing_workspace.id,
            WorkspaceMembership.user_id == invited.id,
        )
    )
    assert skipped_membership is None


async def test_accept_invitation_by_token_rejects_different_user_email(
    db_session: AsyncSession,
) -> None:
    owner = build_user(email="owner@example.com")
    wrong_user = build_user(email="wrong@example.com")
    workspace = build_workspace(slug="team-workspace", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )
    raw_token = "raw-invite-token-12345"
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email="invited@example.com",
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, wrong_user, workspace, owner_membership, invitation])
    await db_session.flush()

    with pytest.raises(AuthorizationError, match="different email address"):
        await accept_invitation_by_token(
            db_session,
            request=None,
            actor=wrong_user,
            token=raw_token,
        )

    assert invitation.accepted_at is None
    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == wrong_user.id,
        )
    )
    assert membership is None
