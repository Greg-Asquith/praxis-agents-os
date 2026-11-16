# apps/api/integrations/outlook_calendar/operations/respond_to_event.py

"""Accepts, tentatively accepts, or declines an invitation."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import CalendarWriteState, event_path

RESPONSE_ACTIONS = {"accept": "accept", "tentative": "tentativelyAccept", "decline": "decline"}


async def respond_to_event(
    client: MicrosoftGraphClient,
    *,
    state: CalendarWriteState,
    calendar_id: str,
    response: str,
    comment: str,
    send_response: bool,
) -> None:
    if state.event_id is None:
        raise ValueError("Responding requires an event reference.")
    await client.post(
        f"{event_path(calendar_id, state.event_id)}/{RESPONSE_ACTIONS[response]}",
        operation="respond_to_event",
        policy=IntegrationRequestPolicy.MUTATION,
        json={"comment": comment, "sendResponse": send_response},
    )
    state.applied = True
