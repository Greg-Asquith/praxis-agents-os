"""Account-boundary invariants for OAuth login and linking."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import UserAuth
from services.auth.oauth.complete_oauth_link import complete_oauth_link
from services.auth.oauth.utils import create_oauth_link_state, upsert_oauth_user
from services.auth.schemas import OAuthCallbackRequest
from tests.factories import build_user


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
