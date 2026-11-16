# apps/api/integrations/outlook_calendar/operations/delete_event.py

"""Deletes an event without sending cancellations."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import CalendarWriteState, event_path


async def delete_event(
    client: MicrosoftGraphClient, *, state: CalendarWriteState, calendar_id: str
) -> None:
    if state.event_id is None:
        raise ValueError("Deleting requires an event reference.")
    await client.delete(
        event_path(calendar_id, state.event_id),
        operation="delete_event",
        policy=IntegrationRequestPolicy.MUTATION,
    )
    state.applied = True
