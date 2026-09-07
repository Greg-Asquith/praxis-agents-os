# apps/api/integrations/outlook_calendar/discover_resources.py

"""Discover calendars represented by an Outlook Calendar grant."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import (
    MicrosoftGraphClient,
    fixed_access_token,
    graph_string,
    required_graph_string,
)
from services.integrations.plugin import DiscoveredIntegrationResource

CALENDARS_WRITE_SCOPE = "Calendars.ReadWrite"
_MAX_CALENDARS = 200
_MAX_PAGES = 20


async def discover_resources(
    access_token: str,
    _principal_label: str | None = None,
    pacing_key: str = "",
) -> tuple[DiscoveredIntegrationResource, ...]:
    client = MicrosoftGraphClient(
        fixed_access_token(access_token),
        provider_key="outlook_calendar",
        pacing_key=pacing_key,
    )
    user = await client.get(
        "/me",
        operation="discover_outlook_calendar_owner",
        policy=IntegrationRequestPolicy.READ,
        params={"$select": "id"},
    )
    mailbox_id = required_graph_string(user, "id", provider_key="outlook_calendar")
    mailbox_settings = await client.get(
        "/me/mailboxSettings",
        operation="discover_outlook_calendar_settings",
        policy=IntegrationRequestPolicy.READ,
        params={"$select": "timeZone"},
    )
    time_zone = graph_string(mailbox_settings, "timeZone")
    calendars = await client.paginate(
        "/me/calendars",
        operation="discover_outlook_calendars",
        params={
            "$select": "id,name,isDefaultCalendar,canEdit,canViewPrivateItems,owner",
            "$top": 100,
        },
        max_items=_MAX_CALENDARS,
        max_pages=_MAX_PAGES,
    )
    return tuple(
        resource
        for calendar in calendars
        if (resource := _calendar_resource(calendar, mailbox_id=mailbox_id, time_zone=time_zone))
        is not None
    )


def _calendar_resource(
    calendar: dict[str, Any],
    *,
    mailbox_id: str,
    time_zone: str,
) -> DiscoveredIntegrationResource | None:
    calendar_id = graph_string(calendar, "id")
    name = graph_string(calendar, "name")
    if not calendar_id or not name:
        return None
    metadata: dict[str, object] = {
        "is_default": calendar.get("isDefaultCalendar") is True,
        "mailbox_id": mailbox_id,
        "can_view_private_items": calendar.get("canViewPrivateItems") is True,
    }
    owner = calendar.get("owner")
    owner_address = graph_string(owner, "address")
    if owner_address:
        metadata["owner_address"] = owner_address
    if time_zone:
        metadata["time_zone"] = time_zone
    return DiscoveredIntegrationResource(
        resource_type="outlook_calendar",
        external_id=calendar_id,
        display_name=name,
        parent_external_id=mailbox_id,
        writable=calendar.get("canEdit") is True,
        required_write_scopes=(CALENDARS_WRITE_SCOPE,),
        permissions_metadata=metadata,
    )
