# apps/api/tests/integrations/outlook_calendar/test_outlook_calendar_entity_resolvers.py

"""Outlook event choices stay inside the selected calendars."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from integrations.outlook_calendar.entity_resolvers import event
from integrations.outlook_calendar.references import OutlookEventReference
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.outlook_calendar.support import entry


async def test_event_outside_the_selected_calendars_resolves_without_provider_io(monkeypatch):
    factory = AsyncMock()
    monkeypatch.setattr(event, "calendar_client_for_principal", factory)
    ctx = SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry("work"),)))
    reference = OutlookEventReference(calendar_id="other", event_id="event-1", label="Event")
    assert await event.resolve_events(ctx, [reference.model_dump()], {}) == ()
    factory.assert_not_awaited()
