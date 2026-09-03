# apps/api/services/integrations/oauth/resolve_external_principal.py

"""Resolve a stable external identity through the provider's OAuth protocol."""

from typing import Any

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationValidationError,
)
from services.integrations.http import IntegrationRequestPolicy, request_with_retries
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config
from services.integrations.oauth.utils import parse_oauth_json_object
from services.integrations.plugin import ExternalPrincipal

GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


async def resolve_external_principal(
    *,
    provider_key: str,
    access_token: str,
    token_payload: dict[str, Any] | None = None,
) -> ExternalPrincipal:
    protocol = resolve_provider_oauth_config(provider_key).protocol
    if protocol.identity_source == "google_userinfo":
        return await _fetch_google_userinfo(
            provider_key=provider_key,
            access_token=access_token,
        )

    try:
        if token_payload is not None and protocol.extract_identity is not None:
            try:
                return protocol.extract_identity(token_payload)
            except IntegrationAuthError as exc:
                if exc.error_code != "identity_token_unavailable":
                    raise
        if protocol.fetch_identity is None:
            raise IntegrationValidationError(
                "External identity lookup is not configured for this provider",
                provider_key=provider_key,
                operation="resolve_external_principal",
            )
        return await protocol.fetch_identity(access_token)
    except IntegrationError:
        raise
    except Exception:
        raise IntegrationAuthError(
            "Provider identity response could not be resolved",
            provider_key=provider_key,
            operation="resolve_external_principal",
        ) from None


async def _fetch_google_userinfo(*, provider_key: str, access_token: str) -> ExternalPrincipal:
    response = await request_with_retries(
        "GET",
        GOOGLE_USERINFO_URL,
        operation="oauth_userinfo",
        provider_key=provider_key,
        policy=IntegrationRequestPolicy.READ,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    payload = parse_oauth_json_object(
        response,
        provider_key=provider_key,
        operation="oauth_userinfo",
    )
    external_id = payload.get("sub")
    if not external_id:
        raise IntegrationAuthError(
            "Provider identity response did not include a stable identifier",
            provider_key=provider_key,
            operation="oauth_userinfo",
        )
    label = payload.get("email")
    return ExternalPrincipal(str(external_id), str(label) if label else None)
