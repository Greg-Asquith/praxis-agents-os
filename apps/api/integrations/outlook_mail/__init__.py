# apps/api/integrations/outlook_mail/__init__.py

"""Outlook Mail provider manifest contribution."""

import re

from services.integrations.manifest import IntegrationProviderManifest
from services.integrations.microsoft_graph import entra_oauth_config
from services.integrations.plugin import (
    IntegrationPreviewDefinition,
    IntegrationProviderPlugin,
    OAuthClientConfig,
)

from .discover_resources import discover_resources
from .entity_resolvers import OUTLOOK_ATTACHMENT_RESOLVER, OUTLOOK_MESSAGE_RESOLVER
from .operations.preview_message import fetch_message_preview
from .settings import outlook_mail_settings
from .tools import TOOL_DEFINITIONS

OUTLOOK_MAIL_OAUTH_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "User.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "MailboxSettings.Read",
    "People.Read",
)


def oauth_config() -> OAuthClientConfig:
    """Return Outlook Mail's isolated Entra application configuration."""
    return entra_oauth_config(
        client_id=outlook_mail_settings.OUTLOOK_MAIL_OAUTH_CLIENT_ID,
        client_secret=outlook_mail_settings.OUTLOOK_MAIL_OAUTH_CLIENT_SECRET,
        tenant_override=outlook_mail_settings.OUTLOOK_MAIL_OAUTH_TENANT,
    )


PROVIDER = IntegrationProviderPlugin(
    manifest=IntegrationProviderManifest(
        provider_key="outlook_mail",
        display_name="Outlook Mail",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=OUTLOOK_MAIL_OAUTH_SCOPES,
        resource_types=("outlook_mailbox",),
        requires_discovery=True,
        connect_help=(
            "Your organization's administrator must configure and approve Outlook Mail before "
            "you connect."
        ),
        capability_flags=frozenset({"read", "write"}),
        event_delivery="none",
    ),
    discover_resources=discover_resources,
    oauth_config=oauth_config,
    tool_definitions=TOOL_DEFINITIONS,
    entity_resolvers=(OUTLOOK_MESSAGE_RESOLVER, OUTLOOK_ATTACHMENT_RESOLVER),
    preview_definitions=(
        IntegrationPreviewDefinition(
            kind="outlook_message",
            operation="preview_message",
            fetch=fetch_message_preview,
            ref_pattern=re.compile(r"[A-Za-z0-9_+/=-]{1,512}"),
        ),
    ),
)
