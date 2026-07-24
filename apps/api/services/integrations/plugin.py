# apps/api/services/integrations/plugin.py

"""Provider contribution contract used by the settings-driven loader."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import SecretStr

from services.integrations.manifest import IntegrationProviderManifest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.integrations import (
        IntegrationConnection,
        IntegrationEvent,
        IntegrationResource,
        IntegrationWebhook,
    )
    from services.agents.runtime.tools.contract import RuntimeToolDefinition


@dataclass(frozen=True)
class DiscoveredIntegrationResource:
    """Provider-neutral resource returned by a discovery implementation."""

    resource_type: str
    external_id: str
    display_name: str
    parent_external_id: str | None = None
    writable: bool = False
    required_write_scopes: tuple[str, ...] = ()
    permissions_metadata: dict[str, object] | None = None


DiscoverResourcesFn = Callable[
    [str, str | None], Awaitable[Sequence[DiscoveredIntegrationResource]]
]


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
class IntegrationPreviewPayload:
    """Raw provider content returned to the engine preview boundary."""

    content_type: Literal["html", "text"]
    content: str
    meta: dict[str, object]


IntegrationPreviewFetchFn = Callable[
    ["AsyncSession", "IntegrationConnection", str],
    Awaitable[IntegrationPreviewPayload],
]


@dataclass(frozen=True)
class IntegrationPreviewDefinition:
    """One provider-owned preview kind exposed through the generic route."""

    kind: str
    operation: str
    fetch: IntegrationPreviewFetchFn


@dataclass(frozen=True)
class IntegrationEventRequest:
    """Provider-neutral metadata and exact bytes at the verification boundary."""

    headers: Mapping[str, str]
    raw_body: bytes
    payload_digest: str
    request_url: str


@dataclass(frozen=True)
class VerifiedIntegrationEvent:
    """Authenticated provider receipt normalized before central persistence."""

    connection_id: UUID
    external_event_id: str
    external_resource_id: str | None
    event_type: str
    dedup_key: str
    payload: dict[str, object]


@dataclass(frozen=True)
class ProcessedIntegrationEvent:
    """Bounded provider processing result persisted on the central event row."""

    payload: dict[str, object] | None = None
    discard_reason: str | None = None


VerifyIntegrationEventFn = Callable[
    ["AsyncSession", "IntegrationWebhook", IntegrationEventRequest],
    Awaitable[VerifiedIntegrationEvent],
]
ProcessIntegrationEventFn = Callable[
    ["AsyncSession", "IntegrationWebhook", "IntegrationEvent"],
    Awaitable[ProcessedIntegrationEvent],
]
CreateIntegrationWebhookFn = Callable[
    [
        "AsyncSession",
        "IntegrationConnection",
        "IntegrationResource",
    ],
    Awaitable["IntegrationWebhook"],
]
RefreshIntegrationWebhookFn = Callable[
    ["AsyncSession", "IntegrationWebhook"],
    Awaitable[None],
]
DeleteIntegrationWebhookFn = Callable[
    ["AsyncSession", "IntegrationWebhook"],
    Awaitable[None],
]


@dataclass(frozen=True)
class IntegrationEventDefinition:
    """Provider-owned verification, processing, and webhook lifecycle seams."""

    verify: VerifyIntegrationEventFn
    process: ProcessIntegrationEventFn
    create_webhook: CreateIntegrationWebhookFn
    refresh_webhook: RefreshIntegrationWebhookFn
    delete_webhook: DeleteIntegrationWebhookFn


@dataclass(frozen=True)
class IntegrationProviderPlugin:
    manifest: IntegrationProviderManifest
    discover_resources: DiscoverResourcesFn | None
    oauth_config: OAuthConfigFn | None = None
    tool_definitions: tuple["RuntimeToolDefinition", ...] = ()
    preview_definitions: tuple[IntegrationPreviewDefinition, ...] = ()
    event_definition: IntegrationEventDefinition | None = None


PROVIDER_PLUGINS: dict[str, IntegrationProviderPlugin] = {}


def register_provider_plugin(plugin: IntegrationProviderPlugin) -> None:
    """Register the enabled provider's non-manifest contributions."""
    provider_key = plugin.manifest.provider_key
    if provider_key in PROVIDER_PLUGINS:
        raise RuntimeError(f"Duplicate integration provider plugin: {provider_key}")
    PROVIDER_PLUGINS[provider_key] = plugin
