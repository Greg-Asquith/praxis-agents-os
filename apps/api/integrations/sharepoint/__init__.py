# apps/api/integrations/sharepoint/__init__.py

"""SharePoint provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.microsoft_graph import entra_oauth_config
from services.integrations.plugin import IntegrationProviderPlugin, OAuthClientConfig

from .discover_resources import discover_resources
from .settings import sharepoint_settings

SHAREPOINT_OAUTH_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "User.Read",
    "Files.Read.All",
    "Sites.Read.All",
)


def oauth_config() -> OAuthClientConfig:
    """Return SharePoint's isolated Entra application configuration."""
    return entra_oauth_config(
        client_id=sharepoint_settings.SHAREPOINT_OAUTH_CLIENT_ID,
        client_secret=sharepoint_settings.SHAREPOINT_OAUTH_CLIENT_SECRET,
        tenant_override=sharepoint_settings.SHAREPOINT_OAUTH_TENANT,
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="sharepoint",
        display_name="SharePoint",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=SHAREPOINT_OAUTH_SCOPES,
        resource_types=("sharepoint_drive",),
        requires_discovery=True,
        connect_help=(
            "Your organization's administrator must configure and approve SharePoint before "
            "you connect."
        ),
        capability_flags=frozenset({"read"}),
        event_delivery="none",
    ),
    discover_resources=discover_resources,
    oauth_config=oauth_config,
)
