# apps/api/services/integrations/oauth/fetch_external_principal.py

"""Fetch a stable identity for a newly authorized external principal."""

from dataclasses import dataclass

from core.exceptions.integration import IntegrationAuthError, IntegrationValidationError
from services.integrations.http import request_with_retries
from services.integrations.oauth.utils import parse_oauth_json_object

GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_PROVIDER_KEYS = frozenset({"gmail", "google_ads"})


@dataclass(frozen=True)
class ExternalPrincipal:
    external_id: str
    label: str | None


async def fetch_external_principal(*, provider_key: str, access_token: str) -> ExternalPrincipal:
    if provider_key not in GOOGLE_PROVIDER_KEYS:
        raise IntegrationValidationError(
            "External identity lookup is not configured for this provider",
            provider_key=provider_key,
            operation="fetch_external_principal",
        )
    response = await request_with_retries(
        "GET",
        GOOGLE_USERINFO_URL,
        operation="oauth_userinfo",
        provider_key=provider_key,
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
