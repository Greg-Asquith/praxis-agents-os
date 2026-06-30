# apps/api/services/auth/oauth/complete_oauth_link.py

"""Complete an OAuth link by attaching a provider identity to the current user."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.oauth_providers.oauth_registry import oauth_registry
from core.exceptions.general import ConflictError, NotFoundError
from core.exceptions.oauth import OAuthAuthenticationError
from models.user import User, UserAuth
from services.audit_events import AuditAction, AuditResourceType, record_user_audit_event
from services.auth.list_user_identities import list_user_identities
from services.auth.oauth.utils import (
    provider_email,
    provider_email_verified,
    provider_user_id_from_profile,
    resolve_provider_redirect_uri,
    token_expires_at,
    verify_oauth_link_state,
)
from services.auth.schemas import IdentitiesResponse, OAuthCallbackRequest
from services.auth.utils import record_auth_security_event
from services.security import SecurityEventType


async def complete_oauth_link(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    provider_name: str,
    payload: OAuthCallbackRequest,
) -> IdentitiesResponse:
    provider_name = provider_name.strip().lower()
    provider = oauth_registry.get_provider(provider_name)
    if provider is None:
        raise NotFoundError("OAuth provider is not configured", resource_type="oauth_provider")

    try:
        state_payload = verify_oauth_link_state(payload.state)
        if state_payload["provider"] != provider_name:
            raise OAuthAuthenticationError(
                "OAuth state provider mismatch", provider=provider_name, endpoint="state"
            )
        if state_payload["user_id"] != str(user.id):
            raise OAuthAuthenticationError(
                "OAuth state user mismatch", provider=provider_name, endpoint="state"
            )

        redirect_uri = resolve_provider_redirect_uri(provider_name, payload.redirect_uri)
        if state_payload["redirect_uri"] != redirect_uri:
            raise OAuthAuthenticationError(
                "OAuth redirect URI mismatch", provider=provider_name, endpoint="state"
            )

        token_payload = await provider.exchange_code(code=payload.code, redirect_uri=redirect_uri)
        access_token = token_payload.get("access_token")
        if not access_token:
            raise OAuthAuthenticationError(
                "OAuth provider did not return an access token",
                provider=provider_name,
                endpoint="token",
            )
        profile = await provider.get_user_info(str(access_token))
    except Exception:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            user_email=user.email,
            details={"provider": provider_name, "intent": "link"},
            committed=True,
        )
        raise

    provider_user_id = provider_user_id_from_profile(provider_name, profile)
    email = provider_email(provider_name, profile)
    if not provider_user_id:
        raise OAuthAuthenticationError(
            "OAuth provider did not return a stable user ID",
            provider=provider_name,
            endpoint="user_info",
        )
    if not email:
        raise OAuthAuthenticationError(
            "OAuth provider did not return a verified email",
            provider=provider_name,
            endpoint="user_info",
        )

    # Reject if this provider identity is already linked to a different account.
    existing = await db.execute(
        select(UserAuth)
        .where(
            UserAuth.provider == provider_name,
            UserAuth.provider_user_id == provider_user_id,
            UserAuth.deleted.is_(False),
        )
        .with_for_update()
    )
    existing_record = existing.scalar_one_or_none()
    if existing_record is not None and existing_record.user_id != user.id:
        raise ConflictError(
            f"This {provider_name} account is already linked to another user",
            conflicting_resource="user_auth",
        )

    # Keep one identity per provider per user for a predictable settings view.
    current = await db.execute(
        select(UserAuth).where(
            UserAuth.user_id == user.id,
            UserAuth.provider == provider_name,
            UserAuth.deleted.is_(False),
        )
    )
    auth_record = current.scalar_one_or_none()
    if auth_record is not None and auth_record.provider_user_id != provider_user_id:
        raise ConflictError(
            f"A {provider_name} account is already linked. Remove it before linking another.",
            conflicting_resource="user_auth",
        )

    if auth_record is None:
        auth_record = UserAuth(
            user_id=user.id,
            provider=provider_name,
            provider_user_id=provider_user_id,
            email=email,
            email_verified=provider_email_verified(provider_name, profile),
            raw_profile=profile,
        )
        db.add(auth_record)
    else:
        auth_record.email = email
        auth_record.email_verified = provider_email_verified(provider_name, profile)
        auth_record.raw_profile = profile

    auth_record.access_token = str(token_payload.get("access_token") or "")
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        auth_record.refresh_token = str(refresh_token)
    auth_record.token_expires_at = token_expires_at(token_payload)

    await db.flush()
    await record_user_audit_event(
        db,
        action=AuditAction.CREATE,
        user=user,
        actor=user,
        resource_type=AuditResourceType.USER_AUTH,
        details={"provider": provider_name, "intent": "link"},
        request=request,
    )
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_OAUTH_SUCCEEDED,
        request=request,
        user_email=user.email,
        details={"provider": provider_name, "intent": "link"},
    )
    return await list_user_identities(db, user=user)
