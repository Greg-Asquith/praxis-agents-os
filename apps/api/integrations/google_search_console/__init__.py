# apps/api/integrations/google_search_console/__init__.py

"""Google Search Console provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import (
    IntegrationProviderPlugin,
    OAuthClientConfig,
    OAuthProtocol,
)

from .discover_resources import WEBMASTERS_SCOPE, discover_resources
from .settings import google_search_console_settings
from .tools import TOOL_DEFINITIONS

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def oauth_config() -> OAuthClientConfig:
    """Return Google Search Console's isolated OAuth application configuration."""
    return OAuthClientConfig(
        client_id=google_search_console_settings.GOOGLE_SEARCH_CONSOLE_OAUTH_CLIENT_ID,
        client_secret=google_search_console_settings.GOOGLE_SEARCH_CONSOLE_OAUTH_CLIENT_SECRET,
        authorization_url=GOOGLE_AUTHORIZATION_URL,
        token_url=GOOGLE_TOKEN_URL,
        revoke_url=GOOGLE_REVOKE_URL,
        protocol=OAuthProtocol(identity_source="google_userinfo"),
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="google_search_console",
        display_name="Google Search Console",
        auth_modes=("oauth",),
        owner_scope="workspace",
        oauth_scopes=("openid", "email", WEBMASTERS_SCOPE),
        resource_types=("google_search_console_site",),
        requires_discovery=True,
        connect_help=(
            "Connect an account that can view the Search Console properties agents should use."
        ),
        capability_flags=frozenset({"read", "write"}),
    ),
    discover_resources=discover_resources,
    oauth_config=oauth_config,
    tool_definitions=TOOL_DEFINITIONS,
)
