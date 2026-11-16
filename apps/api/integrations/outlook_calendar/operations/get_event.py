# apps/api/integrations/outlook_calendar/operations/get_event.py

"""Reads one event in full, or only the fields a write decides on."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import (
    EVENT_SELECT,
    EVENT_TYPES,
    choice,
    event_detail,
    event_path,
    object_payload,
    zone_header,
)


async def get_event(
    client: MicrosoftGraphClient,
    *,
    calendar_id: str,
    event_id: str,
    time_zone: str,
    can_view_private: bool,
) -> dict:
    payload = object_payload(
        await client.get(
            event_path(calendar_id, event_id),
            operation="read_event",
            policy=IntegrationRequestPolicy.READ,
            params={"$select": f"{EVENT_SELECT},body,seriesMasterId,iCalUId,recurrence"},
            headers=zone_header(time_zone, text_body=True),
        ),
        operation="read_event",
    )
    # The requested ID is authoritative; the scoped path already proved the calendar.
    return event_detail(
        {**payload, "id": event_id}, time_zone=time_zone, can_view_private=can_view_private
    )


async def get_event_state(
    client: MicrosoftGraphClient, *, calendar_id: str, event_id: str, operation: str
) -> dict:
    """Returns the organiser flag, attendee count, and type a write decides on."""
    payload = object_payload(
        await client.get(
            event_path(calendar_id, event_id),
            operation=operation,
            policy=IntegrationRequestPolicy.READ,
            params={"$select": "isOrganizer,attendees,type"},
        ),
        operation=operation,
    )
    attendees = payload.get("attendees")
    return {
        "is_organizer": payload.get("isOrganizer") is True,
        "attendee_count": len(attendees) if isinstance(attendees, list) else 0,
        "type": choice(payload.get("type"), EVENT_TYPES, "singleInstance"),
    }
