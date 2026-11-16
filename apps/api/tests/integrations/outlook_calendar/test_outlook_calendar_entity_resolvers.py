# apps/api/tests/integrations/outlook_calendar/test_outlook_calendar_entity_resolvers.py

"""Outlook event choices stay inside the selected calendars."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from integrations.outlook_calendar.entity_resolvers import event
from integrations.outlook_calendar.references import OutlookEventReference
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.outlook_calendar.support import entry, graph_event


async def test_event_outside_the_selected_calendars_resolves_without_provider_io(monkeypatch):
    factory = AsyncMock()
    monkeypatch.setattr(event, "calendar_client_for_principal", factory)
    ctx = SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry("work"),)))
    reference = OutlookEventReference(calendar_id="other", event_id="event-1", label="Event")
    assert await event.resolve_events(ctx, [reference.model_dump()], {}) == ()
    factory.assert_not_awaited()


async def test_event_search_does_not_match_a_masked_private_subject(monkeypatch):
    client = AsyncMock()
    client.paginate.return_value = [graph_event(subject="Salary review", sensitivity="private")]
    monkeypatch.setattr(event, "calendar_client_for_principal", AsyncMock(return_value=client))
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(entry("team", can_view_private=False),)),
        db=object(),
        actor=object(),
        workspace=object(),
    )

    assert (await event.search_events(ctx, "salary", {}, 20, None)).choices == ()
    [choice] = (await event.search_events(ctx, "private", {}, 20, None)).choices
    assert choice.label == "Private appointment"
