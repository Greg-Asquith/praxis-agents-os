# apps/api/services/integrations/oauth/__init__.py

"""OAuth protocol operations for integration connections."""

from services.integrations.oauth.build_authorization_url import build_authorization_url
from services.integrations.oauth.exchange_authorization_code import (
    exchange_authorization_code,
    refresh_authorization_token,
    revoke_authorization_token,
)
from services.integrations.oauth.resolve_external_principal import resolve_external_principal
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config
from services.integrations.plugin import ExternalPrincipal

__all__ = [
    "ExternalPrincipal",
    "build_authorization_url",
    "exchange_authorization_code",
    "refresh_authorization_token",
    "resolve_external_principal",
    "resolve_provider_oauth_config",
    "revoke_authorization_token",
]
