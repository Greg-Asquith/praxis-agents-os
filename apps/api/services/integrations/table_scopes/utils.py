# apps/api/services/integrations/table_scopes/utils.py

"""Shared lookup and validation helpers for integration table row scopes."""

from core.exceptions.integration import IntegrationValidationError
from models.integrations import IntegrationConnection
from services.integrations.plugin import PROVIDER_PLUGINS

from .adapter import TableScopeAdapter


def table_scope_adapter_for(connection: IntegrationConnection) -> TableScopeAdapter:
    """Returns the provider adapter or rejects unsupported connections."""
    plugin = PROVIDER_PLUGINS.get(connection.provider_key)
    adapter = plugin.table_scope_adapter if plugin is not None else None
    if adapter is None:
        raise IntegrationValidationError(
            "This integration provider does not support table row filters",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="table_scopes",
        )
    return adapter


def table_scope_resource_types(provider_key: str) -> tuple[str, ...]:
    """Returns the registered resource types for a provider."""
    plugin = PROVIDER_PLUGINS.get(provider_key)
    return plugin.manifest.resource_types if plugin is not None else ()
