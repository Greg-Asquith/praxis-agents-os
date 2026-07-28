# apps/api/integrations/bigquery/__init__.py

"""Google BigQuery provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import IntegrationProviderPlugin

from .discover_resources import discover_resources
from .sync_table_schemas import SYNC_TABLE_SCHEMAS_KIND

PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="bigquery",
        display_name="Google BigQuery",
        auth_modes=("service_account",),
        owner_scope="workspace",
        resource_types=("bigquery_dataset",),
        requires_discovery=True,
        capability_flags=frozenset({"read"}),
    ),
    discover_resources=discover_resources,
    metadata_sync_job_kind=SYNC_TABLE_SCHEMAS_KIND,
)
