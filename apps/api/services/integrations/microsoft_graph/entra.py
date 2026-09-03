# apps/api/services/integrations/microsoft_graph/entra.py

"""Global-cloud Microsoft Entra OAuth protocol construction."""

import re
from functools import partial
from uuid import UUID

from pydantic import SecretStr

from core.settings import settings
from services.integrations.plugin import OAuthClientConfig, OAuthProtocol

from .errors import classify_entra_token_error

ENTRA_HOST = "https://login.microsoftonline.com"
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)


def validate_entra_tenant(value: str) -> str:
    """Validate a global-cloud tenant identifier or hosted authority."""
    normalized = value.strip().lower()
    if normalized == "organizations":
        return normalized
    if normalized in {"", "common", "consumers"}:
        raise ValueError("Microsoft Graph tenant must identify an organization")
    try:
        return str(UUID(normalized))
    except ValueError:
        if _DOMAIN_PATTERN.fullmatch(normalized):
            return normalized
    raise ValueError("Microsoft Graph tenant must be a tenant ID or verified domain")


def authorization_url(tenant: str) -> str:
    return f"{ENTRA_HOST}/{validate_entra_tenant(tenant)}/oauth2/v2.0/authorize"


def token_url(tenant: str) -> str:
    return f"{ENTRA_HOST}/{validate_entra_tenant(tenant)}/oauth2/v2.0/token"


def resolve_entra_tenant(package_override: str) -> str:
    """Resolve and validate a package tenant override or the shared setting."""
    return validate_entra_tenant(package_override or settings.MICROSOFT_GRAPH_TENANT)


def entra_oauth_protocol(
    *,
    client_id: str,
    expected_tenant_id: str | None,
) -> OAuthProtocol:
    """Build the provider-declared OAuth protocol for Microsoft Graph."""
    from .identity import extract_token_identity, fetch_graph_identity

    return OAuthProtocol(
        authorization_params=(("response_mode", "query"), ("prompt", "select_account")),
        scope_parameter=True,
        scope_separator=" ",
        scope_resource_prefix="https://graph.microsoft.com/",
        pkce="s256",
        token_auth="client_secret_post",  # noqa: S106 - protocol enum
        token_encoding="form",  # noqa: S106 - protocol enum
        identity_source="provider",
        extract_identity=partial(
            extract_token_identity,
            client_id=client_id,
            expected_tenant_id=expected_tenant_id,
        ),
        fetch_identity=fetch_graph_identity,
        revoke_token="none",  # noqa: S106 - protocol enum
        classify_token_error=classify_entra_token_error,
    )


def entra_oauth_config(
    *,
    client_id: str,
    client_secret: SecretStr,
    tenant_override: str,
) -> OAuthClientConfig:
    """Build one package-owned client configuration on the shared Entra protocol."""
    configured_tenant = tenant_override or settings.MICROSOFT_GRAPH_TENANT
    if not configured_tenant and not client_id.strip():
        tenant = "organizations"
    else:
        tenant = validate_entra_tenant(configured_tenant)
    try:
        expected_tenant_id = str(UUID(tenant))
    except ValueError:
        expected_tenant_id = None
    return OAuthClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        authorization_url=authorization_url(tenant),
        token_url=token_url(tenant),
        revoke_url="",
        protocol=entra_oauth_protocol(
            client_id=client_id,
            expected_tenant_id=expected_tenant_id,
        ),
    )
