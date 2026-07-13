# apps/api/services/integrations/providers_view.py

"""Read the enabled provider catalog without exposing configuration secrets."""

from core.settings import settings
from services.integrations.connections.schemas import ProviderRead
from services.integrations.manifest import PROVIDER_MANIFESTS, IntegrationProviderManifest
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config


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
            capability_flags=manifest.capability_flags,
            requires_discovery=manifest.requires_discovery,
            configured=is_provider_configured(manifest),
        )
        for manifest in sorted(PROVIDER_MANIFESTS.values(), key=lambda item: item.display_name)
    ]


def is_provider_configured(manifest: IntegrationProviderManifest) -> bool:
    if "oauth" not in manifest.auth_modes:
        return True
    oauth_config = resolve_provider_oauth_config(manifest.provider_key)
    return bool(
        oauth_config.client_id.strip()
        and oauth_config.client_secret.get_secret_value()
        and settings.INTEGRATIONS_OAUTH_REDIRECT_URI.strip()
    )
