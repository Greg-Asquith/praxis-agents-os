# apps/api/services/auth/create_oauth_authorization_url.py

"""Create an OAuth authorization URL for the frontend."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.oauth_providers.oauth_registry import oauth_registry
from core.exceptions.general import NotFoundError
from services.auth.oauth.utils import create_oauth_state, resolve_provider_redirect_uri
from services.auth.schemas import OAuthAuthorizationUrlRequest, OAuthAuthorizationUrlResponse
from services.auth.utils import record_auth_security_event
from services.security import SecurityEventType


async def create_oauth_authorization_url(
    db: AsyncSession,
    *,
    request: Request,
    provider_name: str,
    payload: OAuthAuthorizationUrlRequest,
) -> OAuthAuthorizationUrlResponse:
    provider_name = provider_name.strip().lower()
    provider = oauth_registry.get_provider(provider_name)
    if provider is None:
        # committed: this path returns 404, which rolls back the request session.
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_OAUTH_FAILED,
            request=request,
            details={"provider": provider_name, "reason": "provider_not_configured"},
            committed=True,
        )
        raise NotFoundError("OAuth provider is not configured", resource_type="oauth_provider")

    redirect_uri = resolve_provider_redirect_uri(provider_name, payload.redirect_uri)
    state, expires_at = create_oauth_state(
        provider_name=provider_name,
        redirect_uri=redirect_uri,
        next_path=payload.next_path,
    )
    authorization_url = await provider.get_authorization_url(state=state, redirect_uri=redirect_uri)

    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_OAUTH_STARTED,
        request=request,
        details={"provider": provider_name, "redirect_uri": redirect_uri},
    )
    return OAuthAuthorizationUrlResponse(
        provider=provider_name,
        authorization_url=authorization_url,
        state=state,
        expires_at=expires_at,
    )
