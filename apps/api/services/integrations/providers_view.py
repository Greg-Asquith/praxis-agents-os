# apps/api/services/integrations/providers_view.py

"""Read the enabled provider catalog without exposing configuration secrets."""

from core.settings import settings
from services.integrations.connections.schemas import ProviderRead
from services.integrations.manifest import PROVIDER_MANIFESTS, IntegrationProviderManifest
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config
from services.integrations.plugin import PROVIDER_PLUGINS


def list_providers() -> list[ProviderRead]:
    return [
        ProviderRead(
            provider_key=manifest.provider_key,
            display_name=manifest.display_name,
            auth_modes=manifest.auth_modes,
            owner_scope=manifest.owner_scope,
            oauth_scopes=manifest.oauth_scopes,
            resource_types=manifest.resource_types,
            required_form_fields=manifest.required_form_fields,
            connect_help=manifest.connect_help,
            capability_flags=manifest.capability_flags,
            requires_discovery=manifest.requires_discovery,
            table_scopes_supported=_table_scopes_supported(manifest.provider_key),
            knowledge_source_supported=_knowledge_source_supported(manifest.provider_key),
            knowledge_source_resource_types=_knowledge_source_resource_types(manifest.provider_key),
            configured=is_provider_configured(manifest),
            configured_auth_modes={
                auth_mode: is_auth_mode_configured(manifest, auth_mode)
                for auth_mode in manifest.auth_modes
            },
        )
        for manifest in sorted(PROVIDER_MANIFESTS.values(), key=lambda item: item.display_name)
    ]


def _table_scopes_supported(provider_key: str) -> bool:
    plugin = PROVIDER_PLUGINS.get(provider_key)
    return plugin is not None and plugin.table_scope_adapter is not None


def _knowledge_source_supported(provider_key: str) -> bool:
    plugin = PROVIDER_PLUGINS.get(provider_key)
    return plugin is not None and plugin.knowledge_source is not None


def _knowledge_source_resource_types(provider_key: str) -> tuple[str, ...]:
    plugin = PROVIDER_PLUGINS.get(provider_key)
    if plugin is None or plugin.knowledge_source is None:
        return ()
    return tuple(sorted(plugin.knowledge_source.resource_types))


def is_provider_configured(manifest: IntegrationProviderManifest) -> bool:
    # Preserve the aggregate field for current clients. New clients use the
    # per-mode map so one configured mode cannot imply OAuth is configured.
    if "oauth" in manifest.auth_modes:
        return is_auth_mode_configured(manifest, "oauth")
    return True


def is_auth_mode_configured(
    manifest: IntegrationProviderManifest,
    auth_mode: str,
) -> bool:
    """Report configuration per connect mode without weakening OAuth checks."""
    if auth_mode != "oauth":
        return True
    oauth_config = resolve_provider_oauth_config(manifest.provider_key)
    return bool(
        oauth_config.client_id.strip()
        and oauth_config.client_secret.get_secret_value()
        and settings.INTEGRATIONS_OAUTH_REDIRECT_URI.strip()
    )
