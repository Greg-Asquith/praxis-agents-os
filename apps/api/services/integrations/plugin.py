# apps/api/services/integrations/plugin.py

"""Provider contribution contract used by the settings-driven loader."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from services.integrations.manifest import IntegrationProviderManifest

if TYPE_CHECKING:
    from services.agents.runtime.tools.contract import RuntimeToolDefinition

DiscoverResourcesFn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class OAuthClientConfig:
    """Provider-owned OAuth application credentials and endpoints."""

    client_id: str
    client_secret: SecretStr
    authorization_url: str
    token_url: str
    revoke_url: str


OAuthConfigFn = Callable[[], OAuthClientConfig]


@dataclass(frozen=True)
class IntegrationProviderPlugin:
    manifest: IntegrationProviderManifest
    discover_resources: DiscoverResourcesFn | None
    oauth_config: OAuthConfigFn | None = None
    tool_definitions: tuple["RuntimeToolDefinition", ...] = ()


PROVIDER_PLUGINS: dict[str, IntegrationProviderPlugin] = {}


def register_provider_plugin(plugin: IntegrationProviderPlugin) -> None:
    """Register the enabled provider's non-manifest contributions."""
    provider_key = plugin.manifest.provider_key
    if provider_key in PROVIDER_PLUGINS:
        raise RuntimeError(f"Duplicate integration provider plugin: {provider_key}")
    PROVIDER_PLUGINS[provider_key] = plugin
