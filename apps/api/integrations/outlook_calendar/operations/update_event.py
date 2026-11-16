# apps/api/integrations/outlook_calendar/operations/update_event.py

"""Patches an event's listed fields, which sends an update to its attendees."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import CalendarWriteState, event_path


async def update_event(
    client: MicrosoftGraphClient,
    *,
    state: CalendarWriteState,
    calendar_id: str,
    changes: dict[str, Any],
) -> None:
    if state.event_id is None:
        raise ValueError("Updating requires an event reference.")
    state.updated(
        await client.patch(
            event_path(calendar_id, state.event_id),
            operation="update_event",
            policy=IntegrationRequestPolicy.MUTATION,
            json=changes,
        )
    )
