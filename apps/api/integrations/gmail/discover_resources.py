# apps/api/integrations/gmail/discover_resources.py

"""Discover the authenticated Gmail mailbox."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import DiscoveredIntegrationResource

from .client import GmailClient

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


async def discover_resources(access_token: str, _principal_label: str | None = None):
    async def resolve_token(_force: bool) -> str:
        return access_token

    payload = await GmailClient(resolve_token).get(
        "users/me/profile",
        operation="discover_mailbox",
        policy=IntegrationRequestPolicy.READ,
    )
    email_address = str(payload.get("emailAddress", "")).strip()
    return (
        DiscoveredIntegrationResource(
            resource_type="gmail_mailbox",
            external_id=email_address,
            display_name=email_address,
            writable=True,
            required_write_scopes=(GMAIL_SEND_SCOPE,),
            permissions_metadata={"required_write_scopes": [GMAIL_SEND_SCOPE]},
        ),
    )
