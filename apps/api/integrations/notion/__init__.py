# apps/api/integrations/notion/__init__.py

"""Notion provider manifest contribution."""

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.plugin import (
    IntegrationProviderPlugin,
    OAuthClientConfig,
    OAuthProtocol,
)

from .client import NOTION_API_VERSION
from .discover_resources import discover_resources
from .entity_resolvers import ENTITY_RESOLVERS
from .identity import extract_token_identity, fetch_token_identity
from .settings import notion_settings
from .tools import TOOL_DEFINITIONS

NOTION_AUTHORIZATION_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
NOTION_REVOKE_URL = "https://api.notion.com/v1/oauth/revoke"

NOTION_OAUTH_PROTOCOL = OAuthProtocol(
    authorization_params=(("owner", "user"),),
    scope_parameter=False,
    pkce="none",
    token_auth="client_secret_basic",  # noqa: S106 - protocol enum, not a credential
    token_encoding="json",  # noqa: S106 - protocol enum, not a credential
    identity_source="provider",
    extract_identity=extract_token_identity,
    fetch_identity=fetch_token_identity,
    request_headers=(("Notion-Version", NOTION_API_VERSION),),
    revoke_token="access",  # noqa: S106 - protocol enum, not a credential
)


def oauth_config() -> OAuthClientConfig:
    """Return Notion's public integration OAuth configuration."""
    return OAuthClientConfig(
        client_id=notion_settings.NOTION_OAUTH_CLIENT_ID,
        client_secret=notion_settings.NOTION_OAUTH_CLIENT_SECRET,
        authorization_url=NOTION_AUTHORIZATION_URL,
        token_url=NOTION_TOKEN_URL,
        revoke_url=NOTION_REVOKE_URL,
        protocol=NOTION_OAUTH_PROTOCOL,
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="notion",
        display_name="Notion",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=(),
        resource_types=("notion_workspace",),
        requires_discovery=True,
        connect_help=(
            "Choose the pages this connection can access in Notion. The public integration "
            "needs read, insert, and update content capabilities."
        ),
        capability_flags=frozenset({"read", "write"}),
        event_delivery="none",
    ),
    discover_resources=discover_resources,
    oauth_config=oauth_config,
    tool_definitions=TOOL_DEFINITIONS,
    entity_resolvers=ENTITY_RESOLVERS,
)
