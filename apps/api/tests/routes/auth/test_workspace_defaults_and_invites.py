# apps/api/tests/routes/auth/test_workspace_defaults_and_invites.py

"""Route tests for default workspace persistence and sign-in invitation handling."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.audit_event import AuditEvent
from models.security import SecurityEvent
from models.user import User
from models.workspace import WorkspaceInvitation, WorkspaceMembership, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.security import SecurityEventType
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio

ORIGIN = "http://localhost:3000"
PASSWORD = "StrongerPassword123!"


async def test_login_accepts_pending_invitation_and_records_security_event(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = build_user(email="owner@example.com")
    invited = build_user(email="invited@example.com", password=PASSWORD)
    workspace = build_workspace(slug="client-team", name="Client Team", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited.email,
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("pending-invite-token"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, invited, workspace, owner_membership, invitation])
    await db_session.flush()
    workspace_id = workspace.id
    invited_id = invited.id
    invited_email = invited.email
    invitation_id = invitation.id
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/auth/login",
        headers={"origin": ORIGIN},
        json={"email": invited_email, "password": PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requires_twofa"] is False
    assert body["user"]["email"] == invited_email

    db_session.expire_all()
    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == invited_id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.ADMIN.value

    security_event = await db_session.scalar(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.WORKSPACE_INVITATION_ACCEPTED.value,
            SecurityEvent.user_email == invited_email,
        )
    )
    assert security_event is not None
    assert security_event.details["invitation_id"] == str(invitation_id)


async def test_login_with_twofa_accepts_invitation_only_after_totp_verification(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = build_user(email="owner@example.com")
    invited = build_user(email="totp-invited@example.com", password=PASSWORD)
    secret = invited.generate_totp_secret()
    invited.enable_totp()
    workspace = build_workspace(slug="totp-team", name="TOTP Team", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited.email,
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token("totp-pending-invite-token"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, invited, workspace, owner_membership, invitation])
    await db_session.flush()
    workspace_id = workspace.id
    invited_id = invited.id
    invited_email = invited.email
    invitation_id = invitation.id
    await db_session.commit()

    login_response = await db_async_client.post(
        "/api/v1/auth/login",
        headers={"origin": ORIGIN},
        json={"email": invited_email, "password": PASSWORD},
    )

    assert login_response.status_code == 200
    assert login_response.json()["requires_twofa"] is True
    assert login_response.json()["user"] is None

    db_session.expire_all()
    membership_before_totp = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == invited_id,
        )
    )
    assert membership_before_totp is None
    refreshed_invitation = await db_session.get(WorkspaceInvitation, invitation_id)
    assert refreshed_invitation is not None
    assert refreshed_invitation.accepted_at is None

    verify_response = await db_async_client.post(
        "/api/v1/auth/totp/verify",
        headers={"origin": ORIGIN, "x-csrf-token": db_async_client.cookies.get("csrf", "")},
        json={"token": pyotp.TOTP(secret).now()},
    )

    assert verify_response.status_code == 200
    assert verify_response.json()["requires_twofa"] is False

    db_session.expire_all()
    membership_after_totp = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == invited_id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership_after_totp is not None
    assert membership_after_totp.role == WorkspaceRole.MEMBER.value


async def test_patch_auth_me_persists_default_workspace_and_records_audit(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = build_user(email="switcher@example.com")
    first_workspace = build_workspace(slug="first-team", name="First Team", is_personal=False)
    second_workspace = build_workspace(slug="second-team", name="Second Team", is_personal=False)
    first_membership = build_workspace_membership(
        workspace_id=first_workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    second_membership = build_workspace_membership(
        workspace_id=second_workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    user.default_workspace_id = first_workspace.id
    user_id = user.id
    second_workspace_id = second_workspace.id
    db_session.add_all(
        [user, first_workspace, second_workspace, first_membership, second_membership]
    )
    await db_session.flush()
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()

    response = await db_async_client.patch(
        "/api/v1/auth/me",
        headers=bearer_headers(session["session_token"]),
        json={"default_workspace_id": str(second_workspace_id)},
    )

    assert response.status_code == 200
    assert response.json()["default_workspace_id"] == str(second_workspace_id)

    db_session.expire_all()
    refreshed_user = await db_session.get(User, user_id)
    assert refreshed_user is not None
    assert refreshed_user.default_workspace_id == second_workspace_id

    audit_event = await db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.action == AuditAction.UPDATE.value,
            AuditEvent.resource_type == AuditResourceType.USER.value,
            AuditEvent.resource_id == str(user_id),
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit_event is not None
    assert audit_event.details["fields"] == ["default_workspace_id"]


async def test_patch_auth_me_rejects_invalid_or_null_default_workspace(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = build_user(email="invalid-switcher@example.com")
    member_workspace = build_workspace(slug="member-team", name="Member Team", is_personal=False)
    other_workspace = build_workspace(slug="other-team", name="Other Team", is_personal=False)
    membership = build_workspace_membership(
        workspace_id=member_workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    user.default_workspace_id = member_workspace.id
    db_session.add_all([user, member_workspace, other_workspace, membership])
    await db_session.flush()
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()
    headers = bearer_headers(session["session_token"])

    invalid_response = await db_async_client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"default_workspace_id": str(other_workspace.id)},
    )
    assert invalid_response.status_code == 400
    assert invalid_response.json()["field"] == "default_workspace_id"

    null_response = await db_async_client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"default_workspace_id": None},
    )
    assert null_response.status_code == 400
    assert null_response.json()["field"] == "default_workspace_id"
