# apps/api/services/auth/oauth/complete_oauth_login.py

"""Complete OAuth login by exchanging a provider code server-to-server."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.oauth_providers.oauth_registry import oauth_registry
from core.exceptions.auth import AuthenticationError
from core.exceptions.general import ConflictError, NotFoundError, RateLimitError
from core.exceptions.oauth import OAuthAuthenticationError
from core.rate_limiting import record_login_failure
from services.auth.oauth.utils import (
    clear_oauth_login_binding_cookie,
    provider_email,
    resolve_provider_redirect_uri,
    upsert_oauth_user,
    verify_oauth_login_browser_binding,
    verify_oauth_state,
)
from services.auth.schemas import AuthResponse, OAuthCallbackRequest
from services.auth.utils import (
    enforce_login_failure_limit,
    issue_auth_response,
    record_and_enforce_login_failure,
    record_auth_security_event,
    request_ip,
)
from services.security import SecurityEventType
from utils.redirects import safe_next_path


async def complete_oauth_login(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    provider_name: str,
    payload: OAuthCallbackRequest,
) -> AuthResponse:
    client_ip = request_ip(request)
    provider_name = provider_name.strip().lower()
    provider = oauth_registry.get_provider(provider_name)
    if provider is None:
        await record_and_enforce_login_failure(
            request,
            None,
            anonymous_scope="oauth",
        )
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            details={"provider": provider_name, "reason": "provider_not_configured"},
            committed=True,
        )
        raise NotFoundError("OAuth provider is not configured", resource_type="oauth_provider")

    failure_email: str | None = None
    try:
        state_payload = verify_oauth_state(payload.state)
        verify_oauth_login_browser_binding(
            state_payload,
            request=request,
            provider_name=provider_name,
        )
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
        failure_email = provider_email(provider_name, profile)
        if failure_email is not None:
            await enforce_login_failure_limit(request, failure_email)
        user = await upsert_oauth_user(
            db,
            provider_name=provider_name,
            token_payload=token_payload,
            profile=profile,
            request=request,
        )
    except Exception as exc:
        if isinstance(exc, RateLimitError):
            raise
        if failure_email is None:
            await record_and_enforce_login_failure(
                request,
                None,
                anonymous_scope="oauth",
            )
        else:
            await record_login_failure(client_ip, failure_email)
        details = {"provider": provider_name}
        if isinstance(exc, ConflictError) and exc.details.get("reason") == "oauth_email_collision":
            details["reason"] = "oauth_email_collision"
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            details=details,
            committed=True,
        )
        raise

    await enforce_login_failure_limit(request, user.email)
    if user.is_locked:
        await record_login_failure(client_ip, user.email)
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            user_email=user.email,
            details={"provider": provider_name, "reason": "account_locked"},
            committed=True,
        )
        raise AuthenticationError("Account is temporarily locked")

    clear_oauth_login_binding_cookie(response)
    event_type = (
        SecurityEventType.AUTH_TOTP_CHALLENGE_CREATED
        if user.totp_enabled
        else SecurityEventType.AUTH_OAUTH_SUCCEEDED
    )
    auth_response = await issue_auth_response(
        db,
        request=request,
        response=response,
        user=user,
        event_type=event_type,
        details={"method": "oauth", "provider": provider_name, "requires_twofa": user.totp_enabled},
        require_twofa=user.totp_enabled,
    )
    next_path = state_payload.get("next_path")
    auth_response.next_path = safe_next_path(next_path if isinstance(next_path, str) else None)
    return auth_response
