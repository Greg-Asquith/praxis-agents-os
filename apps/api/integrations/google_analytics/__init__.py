# apps/api/integrations/google_analytics/__init__.py

"""Google Analytics provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin, OAuthClientConfig

from .discover_resources import ANALYTICS_READONLY_SCOPE, discover_resources
from .settings import google_analytics_settings
from .tools import TOOL_DEFINITIONS

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def oauth_config() -> OAuthClientConfig:
    """Return Google Analytics' isolated Google OAuth application configuration."""
    return OAuthClientConfig(
        client_id=google_analytics_settings.GOOGLE_ANALYTICS_OAUTH_CLIENT_ID,
        client_secret=google_analytics_settings.GOOGLE_ANALYTICS_OAUTH_CLIENT_SECRET,
        authorization_url=GOOGLE_AUTHORIZATION_URL,
        token_url=GOOGLE_TOKEN_URL,
        revoke_url=GOOGLE_REVOKE_URL,
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="google_analytics",
        display_name="Google Analytics",
        auth_modes=("oauth", "service_account"),
        owner_scope="workspace",
        oauth_scopes=("openid", "email", ANALYTICS_READONLY_SCOPE),
        resource_types=("google_analytics_property",),
        requires_discovery=True,
        connect_help="Connect an account that can view the Analytics properties agents should use.",
        capability_flags=frozenset({"read"}),
    ),
    discover_resources=discover_resources,
    oauth_config=oauth_config,
    tool_definitions=TOOL_DEFINITIONS,
)
