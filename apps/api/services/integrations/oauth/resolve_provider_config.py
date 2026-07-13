# apps/api/services/integrations/oauth/resolve_provider_config.py

"""Resolve OAuth configuration from an enabled integration provider."""

from core.exceptions.integration import IntegrationValidationError
from services.integrations.plugin import PROVIDER_PLUGINS, OAuthClientConfig


def resolve_provider_oauth_config(provider_key: str) -> OAuthClientConfig:
    """Read provider-owned settings through the enabled-plugin registry."""
    plugin = PROVIDER_PLUGINS.get(provider_key)
    if plugin is None or plugin.oauth_config is None:
        raise IntegrationValidationError(
            "OAuth configuration is not available for this provider",
            provider_key=provider_key,
            operation="oauth_protocol",
        )
    return plugin.oauth_config()
