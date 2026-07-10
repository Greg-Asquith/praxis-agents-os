# apps/api/integrations/airtable/__init__.py

"""Airtable provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin

PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="airtable",
        display_name="Airtable",
        auth_modes=("api_key",),
        owner_scope="workspace",
        resource_types=("airtable_base",),
        # Discovery is advertised when the provider operation lands.
        requires_discovery=False,
        required_form_fields=("api_key",),
        capability_flags=frozenset({"read", "write"}),
        event_delivery="webhook",
    ),
    discover_resources=None,
)
