# apps/api/integrations/gmail/__init__.py

"""Gmail provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin, OAuthClientConfig

from .settings import gmail_settings

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def oauth_config() -> OAuthClientConfig:
    """Return Gmail's isolated Google OAuth application configuration."""
    return OAuthClientConfig(
        client_id=gmail_settings.GMAIL_OAUTH_CLIENT_ID,
        client_secret=gmail_settings.GMAIL_OAUTH_CLIENT_SECRET,
        authorization_url=GOOGLE_AUTHORIZATION_URL,
        token_url=GOOGLE_TOKEN_URL,
        revoke_url=GOOGLE_REVOKE_URL,
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="gmail",
        display_name="Gmail",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=(
            "openid",
            "email",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ),
        capability_flags=frozenset({"read", "write"}),
        event_delivery="pubsub_push",
    ),
    discover_resources=None,
    oauth_config=oauth_config,
)
