# apps/api/integrations/notion/discover_resources.py

"""Discover the Notion workspace represented by one OAuth grant."""

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import DiscoveredIntegrationResource

from .client import NotionClient, fixed_access_token
from .identity import parse_user_identity


async def discover_resources(
    access_token: str,
    principal_label: str | None = None,
    _pacing_key: str = "",
) -> tuple[DiscoveredIntegrationResource, ...]:
    payload = await NotionClient(fixed_access_token(access_token)).get(
        "users/me",
        operation="discover_resources",
        policy=IntegrationRequestPolicy.READ,
    )
    try:
        workspace_id, bot_id, _owner_user_id = parse_user_identity(payload)
    except TypeError:
        raise IntegrationValidationError(
            "Notion workspace discovery returned an invalid response",
            provider_key="notion",
            operation="discover_resources",
        ) from None
    return (
        DiscoveredIntegrationResource(
            resource_type="notion_workspace",
            external_id=workspace_id,
            display_name=principal_label or "Notion workspace",
            writable=True,
            permissions_metadata={"bot_id": bot_id},
        ),
    )
