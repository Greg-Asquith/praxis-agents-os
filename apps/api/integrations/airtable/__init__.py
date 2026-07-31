# apps/api/integrations/airtable/__init__.py

"""Airtable provider contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin

from .discover_resources import discover_resources
from .entity_resolvers import AIRTABLE_RECORD_RESOLVER
from .events import EVENT_DEFINITION
from .tools import TOOL_DEFINITIONS

PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="airtable",
        display_name="Airtable",
        auth_modes=("api_key",),
        owner_scope="workspace",
        resource_types=("airtable_base",),
        requires_discovery=True,
        required_form_fields=("api_key",),
        connect_help=(
            "Use an Airtable personal access token with data.records:read, "
            "data.records:write, schema.bases:read, and webhook:manage scopes."
        ),
        capability_flags=frozenset({"read", "write"}),
        event_delivery="webhook",
    ),
    discover_resources=discover_resources,
    tool_definitions=TOOL_DEFINITIONS,
    entity_resolvers=(AIRTABLE_RECORD_RESOLVER,),
    event_definition=EVENT_DEFINITION,
)
