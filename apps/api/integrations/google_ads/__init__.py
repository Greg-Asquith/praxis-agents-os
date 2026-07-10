# apps/api/integrations/google_ads/__init__.py

"""Google Ads provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin

PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="google_ads",
        display_name="Google Ads",
        auth_modes=("oauth",),
        owner_scope="workspace",
        oauth_scopes=("https://www.googleapis.com/auth/adwords",),
        resource_types=("google_ads_account",),
        # Discovery is advertised when the provider operation lands.
        requires_discovery=False,
        capability_flags=frozenset({"read", "write", "spend"}),
    ),
    discover_resources=None,
)
