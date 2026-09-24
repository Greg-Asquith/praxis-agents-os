# apps/api/integrations/meta_ads/__init__.py

"""Meta Ads provider contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin

from .discover_resources import discover_resources
from .tools import TOOL_DEFINITIONS

PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="meta_ads",
        display_name="Meta Ads",
        auth_modes=("api_key",),
        owner_scope="workspace",
        resource_types=("meta_ads_ad_account",),
        requires_discovery=True,
        required_form_fields=("access_token",),
        connect_help=(
            "Paste a System User access token from your Meta Business Settings. "
            "Select the ad accounts assigned to that system user."
        ),
        capability_flags=frozenset({"read", "write", "spend"}),
        event_delivery="none",
    ),
    discover_resources=discover_resources,
    tool_definitions=TOOL_DEFINITIONS,
)
