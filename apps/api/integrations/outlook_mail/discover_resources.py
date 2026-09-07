# apps/api/integrations/outlook_mail/discover_resources.py

"""Discover the mailbox represented by an Outlook Mail grant."""

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import (
    MicrosoftGraphClient,
    fixed_access_token,
    graph_string,
    required_graph_string,
)
from services.integrations.plugin import (
    DiscoveredIntegrationResource,
    IntegrationDiscoveryResult,
)

MAIL_READ_WRITE_SCOPE = "Mail.ReadWrite"
MAIL_SEND_SCOPE = "Mail.Send"


async def discover_resources(
    access_token: str,
    principal_label: str | None = None,
    pacing_key: str = "",
) -> tuple[DiscoveredIntegrationResource, ...] | IntegrationDiscoveryResult:
    client = MicrosoftGraphClient(
        fixed_access_token(access_token),
        provider_key="outlook_mail",
        pacing_key=pacing_key,
    )
    user = await client.get(
        "/me",
        operation="discover_outlook_mailbox",
        policy=IntegrationRequestPolicy.READ,
        params={"$select": "id,mail,userPrincipalName"},
    )
    mailbox_id = required_graph_string(user, "id", provider_key="outlook_mail")
    principal_name = graph_string(user, "userPrincipalName")
    display_name = graph_string(user, "mail") or principal_name or principal_label
    if not display_name:
        display_name = "Outlook mailbox"

    try:
        mailbox_settings = await client.get(
            "/me/mailboxSettings",
            operation="discover_outlook_mailbox_settings",
            policy=IntegrationRequestPolicy.READ,
            params={"$select": "timeZone"},
        )
    except IntegrationValidationError as exc:
        if exc.error_code != "mailbox_unavailable":
            raise
        return IntegrationDiscoveryResult(resources=(), degraded_reason="mailbox_unavailable")

    metadata: dict[str, object] = {}
    if principal_name:
        metadata["user_principal_name"] = principal_name
    time_zone = graph_string(mailbox_settings, "timeZone")
    if time_zone:
        metadata["time_zone"] = time_zone
    return (
        DiscoveredIntegrationResource(
            resource_type="outlook_mailbox",
            external_id=mailbox_id,
            display_name=display_name,
            writable=True,
            required_write_scopes=(MAIL_READ_WRITE_SCOPE, MAIL_SEND_SCOPE),
            permissions_metadata=metadata,
        ),
    )
