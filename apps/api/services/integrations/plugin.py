# apps/api/services/integrations/plugin.py

"""Provider contribution contract used by the settings-driven loader."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import SecretStr

from core.exceptions.integration import IntegrationError
from services.integrations.manifest import IntegrationProviderManifest

OAUTH_AUTHORIZATION_RESERVED_PARAMETERS = frozenset(
    {
        "client_id",
        "code_challenge",
        "code_challenge_method",
        "redirect_uri",
        "response_type",
        "scope",
        "state",
    }
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.integrations import (
        IntegrationConnection,
        IntegrationEvent,
        IntegrationResource,
        IntegrationWebhook,
    )
    from services.agents.runtime.entity_references.registry import EntityResolverDefinition
    from services.agents.runtime.tools.contract import RuntimeToolDefinition
    from services.integrations.table_scopes.adapter import TableScopeAdapter


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
class ExternalPrincipal:
    """Stable provider identity and bounded non-secret connection metadata."""

    external_id: str
    label: str | None
    connection_metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OAuthProtocol:
    """Provider-declared OAuth wire and identity behavior."""

    authorization_params: tuple[tuple[str, str], ...] = (
        ("access_type", "offline"),
        ("prompt", "consent"),
        ("include_granted_scopes", "false"),
    )
    scope_parameter: bool = True
    scope_separator: str = " "
    pkce: Literal["s256", "none"] = "s256"
    token_auth: Literal["client_secret_post", "client_secret_basic"] = "client_secret_post"
    token_encoding: Literal["form", "json"] = "form"
    identity_source: Literal["google_userinfo", "provider"] = "google_userinfo"
    extract_identity: Callable[[dict[str, Any]], ExternalPrincipal] | None = None
    fetch_identity: Callable[[str], Awaitable[ExternalPrincipal]] | None = None
    request_headers: tuple[tuple[str, str], ...] = ()
    revoke_token: Literal["refresh_or_access", "access"] = "refresh_or_access"


@dataclass(frozen=True)
class OAuthClientConfig:
    """Provider-owned OAuth application credentials and endpoints."""

    client_id: str
    client_secret: SecretStr
    authorization_url: str
    token_url: str
    revoke_url: str
    protocol: OAuthProtocol = field(default_factory=OAuthProtocol)


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
class KnowledgeSourceSearchResult:
    """Provider-neutral Knowledge Base source returned by a title search."""

    reference: dict[str, Any]
    title: str
    url: str
    source_updated_at: datetime | None


@dataclass(frozen=True)
class KnowledgeSourcePreview:
    """Bounded provider source preview returned to the management UI."""

    reference: dict[str, Any]
    external_id: str
    title: str
    url: str
    source_updated_at: datetime | None
    markdown_excerpt: str


@dataclass(frozen=True)
class KnowledgeSourceDocument:
    """Canonical provider document returned to the Knowledge Base pipeline."""

    external_id: str
    title: str
    url: str
    source_updated_at: datetime | None
    markdown: str


class KnowledgeSourceAccessLostError(IntegrationError):
    """Raised when a provider definitively denies or cannot find a source."""

    _status_override = 409
    _title_override = "Knowledge Source Unavailable"


class KnowledgeSourceDisconnectedError(IntegrationError):
    """Raised when a source no longer has a usable connection binding."""

    _status_override = 409
    _title_override = "Knowledge Source Unavailable"


ParseKnowledgeSourceFn = Callable[[str | dict[str, Any]], dict[str, Any]]
SearchKnowledgeSourcesFn = Callable[
    [
        "AsyncSession",
        "IntegrationConnection",
        "IntegrationResource",
        str | None,
        int,
    ],
    Awaitable[Sequence[KnowledgeSourceSearchResult]],
]
PreviewKnowledgeSourceFn = Callable[
    [
        "AsyncSession",
        "IntegrationConnection",
        "IntegrationResource",
        dict[str, Any],
    ],
    Awaitable[KnowledgeSourcePreview],
]
FetchKnowledgeSourceFn = Callable[
    [
        "AsyncSession",
        "IntegrationConnection",
        "IntegrationResource",
        str,
    ],
    Awaitable[KnowledgeSourceDocument],
]


@dataclass(frozen=True)
class IntegrationKnowledgeSourceDefinition:
    """Provider-owned Knowledge Base source operations."""

    resource_types: frozenset[str]
    parse_source: ParseKnowledgeSourceFn
    search: SearchKnowledgeSourcesFn
    preview: PreviewKnowledgeSourceFn
    fetch: FetchKnowledgeSourceFn


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
    metadata_sync_job_kind: str | None = None
    oauth_config: OAuthConfigFn | None = None
    tool_definitions: tuple["RuntimeToolDefinition", ...] = ()
    preview_definitions: tuple[IntegrationPreviewDefinition, ...] = ()
    entity_resolvers: tuple["EntityResolverDefinition", ...] = ()
    event_definition: IntegrationEventDefinition | None = None
    table_scope_adapter: "TableScopeAdapter | None" = None
    knowledge_source: IntegrationKnowledgeSourceDefinition | None = None


PROVIDER_PLUGINS: dict[str, IntegrationProviderPlugin] = {}


def register_provider_plugin(plugin: IntegrationProviderPlugin) -> None:
    """Register the enabled provider's non-manifest contributions."""
    provider_key = plugin.manifest.provider_key
    if provider_key in PROVIDER_PLUGINS:
        raise RuntimeError(f"Duplicate integration provider plugin: {provider_key}")
    PROVIDER_PLUGINS[provider_key] = plugin
