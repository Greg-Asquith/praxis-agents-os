# apps/api/integrations/outlook_calendar/operations/create_event.py

"""Creates one event, which sends invitations to every attendee."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import CalendarWriteState, calendar_path


async def create_event(
    client: MicrosoftGraphClient,
    *,
    state: CalendarWriteState,
    calendar_id: str,
    event: dict[str, Any],
) -> None:
    # The caller's transactionId lets Graph drop a repeated create of the same request.
    state.created(
        await client.post(
            f"{calendar_path(calendar_id)}/events",
            operation="create_event",
            policy=IntegrationRequestPolicy.MUTATION,
            json=event,
        )
    )
