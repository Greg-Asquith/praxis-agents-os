# apps/api/services/integrations/microsoft_graph/identity.py

"""Microsoft Graph delegated-user identity resolution."""

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2

from core.exceptions.integration import IntegrationAuthError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import ExternalPrincipal

from .client import MicrosoftGraphClient, fixed_access_token
from .entra import ENTRA_HOST

_CLOCK_SKEW_SECONDS = 60
_MAX_METADATA_CHARS = 255


def extract_token_identity(
    payload: dict[str, Any],
    *,
    client_id: str,
    expected_tenant_id: str | None,
) -> ExternalPrincipal:
    """Extract a bounded principal from an ID token returned by Entra."""
    claims = _decode_id_token(payload.get("id_token"))
    oid = _uuid_claim(claims, "oid")
    tenant_id = _uuid_claim(claims, "tid")
    if claims.get("aud") != client_id:
        raise _identity_error()
    if claims.get("iss") != f"{ENTRA_HOST}/{tenant_id}/v2.0":
        raise _identity_error()
    expires_at = claims.get("exp")
    if not isinstance(expires_at, (int, float)):
        raise _identity_error()
    if expires_at + _CLOCK_SKEW_SECONDS < datetime.now(UTC).timestamp():
        raise _identity_error()
    if expected_tenant_id is not None and tenant_id.casefold() != expected_tenant_id.casefold():
        raise _identity_error()

    preferred_username = _bounded_claim(claims, "preferred_username")
    metadata = {"tenant_id": tenant_id}
    if preferred_username:
        metadata["user_principal_name"] = preferred_username
    display_name = _bounded_claim(claims, "name")
    if display_name:
        metadata["display_name"] = display_name
    return ExternalPrincipal(
        external_id=oid,
        label=preferred_username,
        connection_metadata=metadata,
    )


async def fetch_graph_identity(
    access_token: str,
    *,
    client: httpx2.AsyncClient | None = None,
) -> ExternalPrincipal:
    """Resolve the delegated user from Microsoft Graph."""
    graph_client = MicrosoftGraphClient(
        fixed_access_token(access_token),
        provider_key="microsoft_graph",
        client=client,
    )
    payload = await graph_client.get(
        "/me",
        operation="fetch_graph_identity",
        policy=IntegrationRequestPolicy.READ,
        params={"$select": "id,mail,userPrincipalName,displayName"},
    )
    if not isinstance(payload, dict):
        raise _identity_error()
    external_id = _uuid_claim(payload, "id")
    principal_name = _bounded_claim(payload, "userPrincipalName")
    mail = _bounded_claim(payload, "mail")
    display_name = _bounded_claim(payload, "displayName")
    metadata: dict[str, str] = {}
    if principal_name:
        metadata["user_principal_name"] = principal_name
    if display_name:
        metadata["display_name"] = display_name
    return ExternalPrincipal(
        external_id=external_id,
        label=mail or principal_name,
        connection_metadata=metadata,
    )


def _decode_id_token(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        raise _identity_error(error_code="identity_token_unavailable")
    parts = value.split(".")
    if len(parts) != 3:
        raise _identity_error(error_code="identity_token_unavailable")
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        claims = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise _identity_error(exc, error_code="identity_token_unavailable") from exc
    if not isinstance(claims, dict):
        raise _identity_error(error_code="identity_token_unavailable")
    return claims


def _uuid_claim(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise _identity_error()
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise _identity_error(exc) from exc


def _bounded_claim(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:_MAX_METADATA_CHARS] or None


def _identity_error(
    original_error: Exception | None = None,
    *,
    error_code: str | None = None,
) -> IntegrationAuthError:
    return IntegrationAuthError(
        "Microsoft identity response was rejected",
        provider_key="microsoft_graph",
        operation="resolve_graph_identity",
        original_error=original_error,
        error_code=error_code,
    )
