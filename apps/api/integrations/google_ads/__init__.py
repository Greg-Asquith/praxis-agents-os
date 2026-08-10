# apps/api/integrations/google_ads/__init__.py

"""Google Ads provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin, OAuthClientConfig

from .discover_resources import discover_resources
from .entity_resolvers import (
    GOOGLE_ADS_AD_GROUP_RESOLVER,
    GOOGLE_ADS_CAMPAIGN_RESOLVER,
    GOOGLE_ADS_SHARED_SET_RESOLVER,
)
from .settings import google_ads_settings
from .tools import TOOL_DEFINITIONS

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def oauth_config() -> OAuthClientConfig:
    """Return Google Ads' isolated Google OAuth application configuration."""
    return OAuthClientConfig(
        client_id=google_ads_settings.GOOGLE_ADS_OAUTH_CLIENT_ID,
        client_secret=google_ads_settings.GOOGLE_ADS_OAUTH_CLIENT_SECRET,
        authorization_url=GOOGLE_AUTHORIZATION_URL,
        token_url=GOOGLE_TOKEN_URL,
        revoke_url=GOOGLE_REVOKE_URL,
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="google_ads",
        display_name="Google Ads",
        auth_modes=("oauth", "service_account"),
        owner_scope="workspace",
        oauth_scopes=(
            "openid",
            "email",
            "https://www.googleapis.com/auth/adwords",
        ),
        resource_types=("google_ads_account",),
        requires_discovery=True,
        capability_flags=frozenset({"read", "write", "spend"}),
    ),
    discover_resources=discover_resources,
    oauth_config=oauth_config,
    tool_definitions=TOOL_DEFINITIONS,
    entity_resolvers=(
        GOOGLE_ADS_AD_GROUP_RESOLVER,
        GOOGLE_ADS_CAMPAIGN_RESOLVER,
        GOOGLE_ADS_SHARED_SET_RESOLVER,
    ),
)
