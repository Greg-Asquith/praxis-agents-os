# apps/api/integrations/outlook_calendar/operations/cancel_event.py

"""Cancels an organiser's meeting, which sends a cancellation to every attendee."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import CalendarWriteState, event_path


async def cancel_event(
    client: MicrosoftGraphClient, *, state: CalendarWriteState, calendar_id: str, comment: str
) -> None:
    if state.event_id is None:
        raise ValueError("Cancelling requires an event reference.")
    await client.post(
        f"{event_path(calendar_id, state.event_id)}/cancel",
        operation="cancel_event",
        policy=IntegrationRequestPolicy.MUTATION,
        json={"comment": comment},
    )
    state.applied = True
