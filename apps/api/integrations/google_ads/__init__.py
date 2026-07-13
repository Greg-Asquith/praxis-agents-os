# apps/api/integrations/google_ads/__init__.py

"""Google Ads provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin, OAuthClientConfig

from .settings import google_ads_settings

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
        auth_modes=("oauth",),
        owner_scope="workspace",
        oauth_scopes=(
            "openid",
            "email",
            "https://www.googleapis.com/auth/adwords",
        ),
        resource_types=("google_ads_account",),
        # Discovery is advertised when the provider operation lands.
        requires_discovery=False,
        capability_flags=frozenset({"read", "write", "spend"}),
    ),
    discover_resources=None,
    oauth_config=oauth_config,
)
