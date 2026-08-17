"""Account-boundary invariants for OAuth login and linking."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError
from core.exceptions.oauth import OAuthAuthenticationError
from core.settings import settings
from models.audit_event import AuditEvent
from models.user import User, UserAuth
from models.workspace import WorkspaceInvitation, WorkspaceMembership, WorkspaceRole
from services.audit_events import AuditResourceType
from services.auth.oauth.complete_oauth_link import complete_oauth_link
from services.auth.oauth.list_oauth_providers import list_oauth_providers
from services.auth.oauth.utils import (
    create_oauth_link_state,
    provider_email,
    provider_email_verified,
    upsert_oauth_user,
)
from services.auth.schemas import OAuthCallbackRequest
from services.auth.utils import issue_auth_response
from services.security import SecurityEventType
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request


def test_microsoft_uses_only_domain_verified_upn_as_email() -> None:
    profile = {
        "mail": "editable-mail@example.com",
        "userPrincipalName": "Verified.UPN@Example.com",
    }

    assert provider_email("microsoft", profile) == "verified.upn@example.com"
    assert provider_email_verified("microsoft", profile) is True
    assert provider_email("microsoft", {"mail": "editable-mail@example.com"}) is None
    assert (
        provider_email(
            "microsoft",
            {"userPrincipalName": "guest_example.com#EXT#@tenant.onmicrosoft.com"},
        )
        is None
    )


async def test_microsoft_guest_upn_is_refused_before_account_lookup() -> None:
    with pytest.raises(OAuthAuthenticationError, match="did not return a verified email"):
        await upsert_oauth_user(
            AsyncMock(),
            provider_name="microsoft",
            token_payload={"access_token": "guest-token"},
            profile={
                "id": "guest-id",
                "mail": "victim@example.com",
                "userPrincipalName": "victim_example.com#EXT#@tenant.onmicrosoft.com",
            },
            request=SimpleNamespace(),
        )


def test_auth_provider_contract_exposes_email_auth_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", False)

    assert list_oauth_providers().email_auth_enabled is False


async def test_verified_configured_super_admin_can_bootstrap_with_oauth(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"oauth-bootstrap-{uuid4()}@example.com"
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)

    user = await upsert_oauth_user(
        db_session,
        provider_name="google",
        token_payload={"access_token": "bootstrap-oauth-token"},
        profile={"sub": "bootstrap-google-id", "email": email, "email_verified": True},
        request=SimpleNamespace(),
    )

    assert user.email == email
    assert await db_session.scalar(select(User).where(User.email == email)) is user


async def test_unverified_email_cannot_bootstrap_super_admin_with_oauth(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"oauth-bootstrap-unverified-{uuid4()}@example.com"
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)

    with pytest.raises(AuthorizationError, match="Signup is disabled"):
        await upsert_oauth_user(
            db_session,
            provider_name="google",
            token_payload={"access_token": "unverified-oauth-token"},
            profile={"sub": "unverified-google-id", "email": email},
            request=SimpleNamespace(),
        )

    assert await db_session.scalar(select(User).where(User.email == email)) is None


async def test_pending_invitation_allows_closed_oauth_signup_and_is_accepted(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invited_email = f"oauth-invited-{uuid4()}@example.com"
    owner = build_user(email=f"oauth-owner-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"oauth-invite-{uuid4()}", is_personal=False)
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
        token_hash=WorkspaceInvitation.hash_raw_token(f"oauth-invite-{uuid4()}"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, workspace, owner_membership, invitation])
    await db_session.flush()
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    request = build_test_request(path="/api/v1/auth/oauth/google/callback")

    user = await upsert_oauth_user(
        db_session,
        provider_name="google",
        token_payload={"access_token": "invited-oauth-token"},
        profile={"sub": "invited-google-id", "email": invited_email, "email_verified": True},
        request=request,
    )
    create_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_id == str(user.id),
            AuditEvent.resource_type == AuditResourceType.USER.value,
            AuditEvent.details["source"].astext == "oauth",
        )
    )
    assert create_event is not None
    assert create_event.details["signup_via"] == "invitation"
    await issue_auth_response(
        db_session,
        request=request,
        response=Response(),
        user=user,
        event_type=SecurityEventType.AUTH_OAUTH_SUCCEEDED,
        details={"method": "oauth", "provider": "google"},
    )

    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.ADMIN.value
    assert invitation.accepted_at is not None


@pytest.mark.parametrize("invitation_state", ["expired", "accepted"])
async def test_unusable_invitation_does_not_allow_closed_oauth_signup(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    invitation_state: str,
) -> None:
    invited_email = f"oauth-{invitation_state}-{uuid4()}@example.com"
    owner = build_user(email=f"oauth-owner-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"oauth-{invitation_state}-{uuid4()}", is_personal=False)
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited_email,
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(f"oauth-{uuid4()}"),
        expires_at=(
            datetime.now(UTC) - timedelta(days=1)
            if invitation_state == "expired"
            else datetime.now(UTC) + timedelta(days=7)
        ),
        accepted_at=datetime.now(UTC) if invitation_state == "accepted" else None,
    )
    db_session.add_all([owner, workspace, invitation])
    await db_session.flush()
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)

    with pytest.raises(AuthorizationError, match="Signup is disabled"):
        await upsert_oauth_user(
            db_session,
            provider_name="google",
            token_payload={"access_token": "unusable-invite-token"},
            profile={"sub": f"google-{uuid4()}", "email": invited_email, "email_verified": True},
            request=SimpleNamespace(),
        )


async def test_unverified_email_and_microsoft_mail_do_not_allow_invited_signup(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invited_email = f"oauth-mail-{uuid4()}@example.com"
    owner = build_user(email=f"oauth-owner-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"oauth-mail-{uuid4()}", is_personal=False)
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=invited_email,
        role=WorkspaceRole.MEMBER.value,
        invited_by=owner.id,
        token_hash=WorkspaceInvitation.hash_raw_token(f"oauth-mail-{uuid4()}"),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([owner, workspace, invitation])
    await db_session.flush()
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)

    with pytest.raises(AuthorizationError, match="Signup is disabled"):
        await upsert_oauth_user(
            db_session,
            provider_name="google",
            token_payload={"access_token": "unverified-token"},
            profile={"sub": f"google-{uuid4()}", "email": invited_email},
            request=SimpleNamespace(),
        )
    with pytest.raises(AuthorizationError, match="Signup is disabled"):
        await upsert_oauth_user(
            db_session,
            provider_name="microsoft",
            token_payload={"access_token": "microsoft-token"},
            profile={
                "id": f"microsoft-{uuid4()}",
                "mail": invited_email,
                "userPrincipalName": f"different-{uuid4()}@example.com",
            },
            request=SimpleNamespace(),
        )

    assert invitation.accepted_at is None


async def test_oauth_login_does_not_merge_an_existing_password_account_by_email(
    db_session: AsyncSession,
) -> None:
    email = f"oauth-collision-{uuid4()}@example.com"
    password = "StrongerPassword123!"
    password_user = build_user(email=email, password=password)
    db_session.add(password_user)
    await db_session.flush()

    with pytest.raises(ConflictError, match="Sign in first, then link this provider"):
        await upsert_oauth_user(
            db_session,
            provider_name="google",
            token_payload={"access_token": "victim-oauth-token"},
            profile={
                "sub": "victim-google-id",
                "email": email,
                "email_verified": True,
            },
            request=SimpleNamespace(),
        )

    assert password_user.verify_password(password)
    auth_record = await db_session.scalar(
        select(UserAuth).where(
            UserAuth.provider == "google",
            UserAuth.provider_user_id == "victim-google-id",
        )
    )
    assert auth_record is None


async def test_authenticated_user_can_explicitly_link_matching_oauth_identity(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"oauth-explicit-link-{uuid4()}@example.com"
    password = "StrongerPassword123!"
    password_user = build_user(email=email, password=password)
    db_session.add(password_user)
    await db_session.flush()

    redirect_uri = "https://app.example.test/oauth/callback"
    state, _ = create_oauth_link_state(
        provider_name="google",
        redirect_uri=redirect_uri,
        user_id=password_user.id,
        next_path=None,
    )
    provider = SimpleNamespace(
        exchange_code=AsyncMock(return_value={"access_token": "linked-oauth-token"}),
        get_user_info=AsyncMock(
            return_value={
                "sub": "linked-google-id",
                "email": email,
                "email_verified": True,
            }
        ),
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_link.oauth_registry.get_provider",
        lambda _provider_name: provider,
    )
    monkeypatch.setattr(
        "services.auth.oauth.complete_oauth_link.resolve_provider_redirect_uri",
        lambda _provider_name, _redirect_uri: redirect_uri,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/oauth/google/link/callback",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "scheme": "https",
            "server": ("app.example.test", 443),
            "query_string": b"",
        }
    )

    result = await complete_oauth_link(
        db_session,
        request=request,
        user=password_user,
        provider_name="google",
        payload=OAuthCallbackRequest(
            code="provider-code",
            state=state,
            redirect_uri=redirect_uri,
        ),
    )

    assert len(result.identities) == 1
    assert result.identities[0].provider == "google"
    auth_record = await db_session.scalar(
        select(UserAuth).where(
            UserAuth.user_id == password_user.id,
            UserAuth.provider == "google",
        )
    )
    assert auth_record is not None
    assert auth_record.provider_user_id == "linked-google-id"
