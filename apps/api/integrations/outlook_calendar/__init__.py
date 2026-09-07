# apps/api/integrations/outlook_calendar/__init__.py

"""Outlook Calendar provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.microsoft_graph import entra_oauth_config
from services.integrations.plugin import IntegrationProviderPlugin, OAuthClientConfig

from .discover_resources import discover_resources
from .settings import outlook_calendar_settings

OUTLOOK_CALENDAR_OAUTH_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "User.Read",
    "Calendars.ReadWrite",
    "Calendars.Read.Shared",
    "MailboxSettings.Read",
    "People.Read",
)


def oauth_config() -> OAuthClientConfig:
    """Return Outlook Calendar's isolated Entra application configuration."""
    return entra_oauth_config(
        client_id=outlook_calendar_settings.OUTLOOK_CALENDAR_OAUTH_CLIENT_ID,
        client_secret=outlook_calendar_settings.OUTLOOK_CALENDAR_OAUTH_CLIENT_SECRET,
        tenant_override=outlook_calendar_settings.OUTLOOK_CALENDAR_OAUTH_TENANT,
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="outlook_calendar",
        display_name="Outlook Calendar",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=OUTLOOK_CALENDAR_OAUTH_SCOPES,
        resource_types=("outlook_calendar",),
        requires_discovery=True,
        connect_help=(
            "Your organization's administrator must configure and approve Outlook Calendar "
            "before you connect."
        ),
        capability_flags=frozenset({"read", "write"}),
        event_delivery="none",
    ),
    discover_resources=discover_resources,
    oauth_config=oauth_config,
)
