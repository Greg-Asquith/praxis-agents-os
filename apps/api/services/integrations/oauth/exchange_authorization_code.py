# apps/api/services/integrations/oauth/exchange_authorization_code.py

"""Exchange and refresh Google-family integration OAuth tokens."""

from typing import Any

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from services.integrations.http import request_with_retries
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config
from services.integrations.oauth.utils import parse_oauth_json_object


async def exchange_authorization_code(
    *, provider_key: str, code: str, code_verifier: str
) -> dict[str, Any]:
    oauth_config = resolve_provider_oauth_config(provider_key)
    response = await request_with_retries(
        "POST",
        oauth_config.token_url,
        operation="oauth_token_exchange",
        provider_key=provider_key,
        data={
            "code": code,
            "client_id": oauth_config.client_id,
            "client_secret": oauth_config.client_secret.get_secret_value(),
            "redirect_uri": settings.INTEGRATIONS_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
    )
    return _parse_token_payload(
        parse_oauth_json_object(
            response,
            provider_key=provider_key,
            operation="oauth_token_exchange",
        ),
        provider_key,
        "oauth_token_exchange",
    )


async def refresh_authorization_token(*, provider_key: str, refresh_token: str) -> dict[str, Any]:
    oauth_config = resolve_provider_oauth_config(provider_key)
    response = await request_with_retries(
        "POST",
        oauth_config.token_url,
        operation="oauth_token_refresh",
        provider_key=provider_key,
        data={
            "refresh_token": refresh_token,
            "client_id": oauth_config.client_id,
            "client_secret": oauth_config.client_secret.get_secret_value(),
            "grant_type": "refresh_token",
        },
    )
    return _parse_token_payload(
        parse_oauth_json_object(
            response,
            provider_key=provider_key,
            operation="oauth_token_refresh",
        ),
        provider_key,
        "oauth_token_refresh",
    )


async def revoke_authorization_token(*, provider_key: str, token: str) -> None:
    oauth_config = resolve_provider_oauth_config(provider_key)
    await request_with_retries(
        "POST",
        oauth_config.revoke_url,
        operation="oauth_token_revoke",
        provider_key=provider_key,
        data={"token": token},
    )


def _parse_token_payload(payload: Any, provider_key: str, operation: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("error"):
        raise IntegrationAuthError(
            "OAuth token response was rejected",
            provider_key=provider_key,
            operation=operation,
        )
    if not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
        raise IntegrationAuthError(
            "OAuth token response did not include an access token",
            provider_key=provider_key,
            operation=operation,
        )
    return payload
