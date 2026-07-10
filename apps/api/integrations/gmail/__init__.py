# apps/api/integrations/gmail/__init__.py

"""Gmail provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin

PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="gmail",
        display_name="Gmail",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=(
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ),
        capability_flags=frozenset({"read", "write"}),
        event_delivery="pubsub_push",
    ),
    discover_resources=None,
)
