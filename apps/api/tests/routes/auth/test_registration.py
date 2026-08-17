# apps/api/tests/routes/auth/test_registration.py

"""Route tests for email/password registration."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.user import User
from models.workspace import WorkspaceInvitation, WorkspaceMembership, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import requires_email_auth


@pytest.mark.asyncio
@requires_email_auth
async def test_register_returns_auth_user_after_workspace_provisioning(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.post(
        "/api/v1/auth/register",
        headers={"origin": "http://localhost:3000"},
        json={
            "email": f"new-user-{uuid4()}@example.com",
            "password": "StrongerPassword123!",
            "display_name": "New User",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"].endswith("@example.com")
    assert body["user"]["display_name"] == "New User"
    assert body["user"]["default_workspace_id"] is not None
    assert body["user"]["updated_at"]
    assert body["session"]["twofa_verified"] is True


@pytest.mark.asyncio
@requires_email_auth
async def test_register_does_not_accept_invitation_for_unverified_email(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    invited_email = f"unverified-invite-{uuid4()}@example.com"
    owner = build_user(email=f"owner-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"unverified-invite-{uuid4()}", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited_email,
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(f"invite-{uuid4()}"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, workspace, owner_membership, invitation])
    await db_session.flush()

    response = await db_async_client.post(
        "/api/v1/auth/register",
        headers={"origin": "http://localhost:3000"},
        json={
            "email": invited_email,
            "password": "StrongerPassword123!",
            "display_name": "Unverified Invitee",
        },
    )

    assert response.status_code == 201
    registered_user = await db_session.scalar(select(User).where(User.email == invited_email))
    assert registered_user is not None
    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == registered_user.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is None
    await db_session.refresh(invitation)
    assert invitation.accepted_at is None


@pytest.mark.asyncio
async def test_closed_signup_accepts_matching_invitation_token(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invited_email = f"token-invite-{uuid4()}@example.com"
    raw_token = f"raw-token-{uuid4()}"
    owner = build_user(email=f"owner-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"token-invite-{uuid4()}", is_personal=False)
    owner_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited_email,
        role=WorkspaceRole.ADMIN.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, workspace, owner_membership, invitation])
    await db_session.flush()
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", True)

    response = await db_async_client.post(
        "/api/v1/auth/register",
        headers={"origin": "http://localhost:3000"},
        json={
            "email": invited_email,
            "password": "StrongerPassword123!",
            "display_name": "Invited User",
            "invitation_token": f"  {raw_token}  ",
        },
    )

    assert response.status_code == 201
    registered_user = await db_session.scalar(select(User).where(User.email == invited_email))
    assert registered_user is not None
    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == registered_user.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.ADMIN.value
    await db_session.refresh(invitation)
    assert invitation.accepted_at is not None


@pytest.mark.asyncio
async def test_closed_signup_rejects_invitation_token_for_another_email(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invited_email = f"right-invite-{uuid4()}@example.com"
    registering_email = f"wrong-invite-{uuid4()}@example.com"
    raw_token = f"raw-token-{uuid4()}"
    owner = build_user(email=f"owner-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"wrong-token-{uuid4()}", is_personal=False)
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited_email,
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, workspace, invitation])
    await db_session.flush()
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", True)

    response = await db_async_client.post(
        "/api/v1/auth/register",
        headers={"origin": "http://localhost:3000"},
        json={
            "email": registering_email,
            "password": "StrongerPassword123!",
            "invitation_token": raw_token,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Signup is disabled"
    assert await db_session.scalar(select(User).where(User.email == registering_email)) is None
    assert invitation.accepted_at is None


@pytest.mark.asyncio
async def test_invitation_token_does_not_override_disabled_email_auth(
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", False)

    response = await db_async_client.post(
        "/api/v1/auth/register",
        headers={"origin": "http://localhost:3000"},
        json={
            "email": f"disabled-email-auth-{uuid4()}@example.com",
            "password": "StrongerPassword123!",
            "invitation_token": f"raw-token-{uuid4()}",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Email authentication is disabled"
