# apps/api/services/auth/complete_oauth_login.py

"""Complete OAuth login by exchanging a provider code server-to-server."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.oauth_providers.oauth_registry import oauth_registry
from core.exceptions.auth import AuthenticationError
from core.exceptions.general import NotFoundError
from core.exceptions.oauth import OAuthAuthenticationError
from services.auth.oauth.utils import (
    resolve_provider_redirect_uri,
    upsert_oauth_user,
    verify_oauth_state,
)
from services.auth.schemas import AuthResponse, OAuthCallbackRequest
from services.auth.utils import issue_auth_response, record_auth_security_event
from services.security import SecurityEventType


async def complete_oauth_login(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    provider_name: str,
    payload: OAuthCallbackRequest,
) -> AuthResponse:
    provider_name = provider_name.strip().lower()
    provider = oauth_registry.get_provider(provider_name)
    if provider is None:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            details={"provider": provider_name, "reason": "provider_not_configured"},
            committed=True,
        )
        raise NotFoundError("OAuth provider is not configured", resource_type="oauth_provider")

    try:
        state_payload = verify_oauth_state(payload.state)
        if state_payload["provider"] != provider_name:
            raise OAuthAuthenticationError(
                "OAuth state provider mismatch", provider=provider_name, endpoint="state"
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
        user = await upsert_oauth_user(
            db,
            provider_name=provider_name,
            token_payload=token_payload,
            profile=profile,
            request=request,
        )
    except Exception:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            details={"provider": provider_name},
            committed=True,
        )
        raise

    if user.is_locked:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            user_email=user.email,
            details={"provider": provider_name, "reason": "account_locked"},
            committed=True,
        )
        raise AuthenticationError("Account is temporarily locked")

    event_type = (
        SecurityEventType.AUTH_TOTP_CHALLENGE_CREATED
        if user.totp_enabled
        else SecurityEventType.AUTH_OAUTH_SUCCEEDED
    )
    return await issue_auth_response(
        db,
        request=request,
        response=response,
        user=user,
        event_type=event_type,
        details={"method": "oauth", "provider": provider_name, "requires_twofa": user.totp_enabled},
        require_twofa=user.totp_enabled,
    )
