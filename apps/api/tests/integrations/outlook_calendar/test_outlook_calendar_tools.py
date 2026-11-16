# apps/api/tests/integrations/outlook_calendar/test_outlook_calendar_tools.py

"""Outlook Calendar tool input bounds, zones, and per-connection queries."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.outlook_calendar.tools.find_meeting_times import (
    outlook_calendar_find_meeting_times,
)
from integrations.outlook_calendar.tools.get_availability import (
    DEFINITION as GET_AVAILABILITY,
    outlook_calendar_get_availability,
)
from integrations.outlook_calendar.tools.list_events import (
    DEFINITION as LIST_EVENTS,
    outlook_calendar_list_events,
)
from tests.integrations.outlook_calendar.support import context, entry, graph_event


@pytest.fixture(autouse=True)
def audit(monkeypatch):
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )


def _client(monkeypatch, module, provider):
    factory = AsyncMock(return_value=provider)
    monkeypatch.setattr(f"integrations.outlook_calendar.tools.{module}.calendar_client", factory)
    return factory


async def test_list_window_over_the_bound_is_rejected_before_any_request(monkeypatch):
    factory = _client(monkeypatch, "list_events", AsyncMock())
    with pytest.raises(ModelRetry, match="at most 62 days"):
        await outlook_calendar_list_events(
            context(entry(), tool_name="outlook_calendar_list_events"),
            start="2026-01-01T00:00:00",
            end="2026-03-05T00:00:00",
        )
    factory.assert_not_awaited()


async def test_find_meeting_times_rejects_21_attendees_before_any_request(monkeypatch):
    factory = _client(monkeypatch, "find_meeting_times", AsyncMock())
    with pytest.raises(ModelRetry, match="1 to 20"):
        await outlook_calendar_find_meeting_times(
            context(entry(), tool_name="outlook_calendar_find_meeting_times"),
            attendees=[f"person{index}@example.com" for index in range(21)],
            start="2026-11-16T09:00:00",
            end="2026-11-20T17:00:00",
        )
    factory.assert_not_awaited()


async def test_omitted_zone_uses_the_mailbox_zone(monkeypatch):
    provider = AsyncMock()
    provider.paginate.return_value = [graph_event()]
    _client(monkeypatch, "list_events", provider)
    result = await outlook_calendar_list_events(
        context(entry(), tool_name="outlook_calendar_list_events"),
        start="2026-11-16T00:00:00",
        end="2026-11-17T00:00:00",
    )
    LIST_EVENTS.output_model.model_validate(result)
    [calendar] = result["results"]
    assert calendar["data"]["time_zone"] == "GMT Standard Time"
    assert calendar["data"]["events"][0]["time_zone"] == "GMT Standard Time"
    assert provider.paginate.call_args.kwargs["headers"] == {
        "Prefer": 'outlook.timezone="GMT Standard Time"'
    }


async def test_mailbox_level_query_runs_once_per_connection(monkeypatch):
    connection_id = uuid4()
    provider = AsyncMock()
    provider.post.return_value = {
        "value": [{"scheduleId": "Dana@Example.com", "availabilityView": "0220"}]
    }
    factory = _client(monkeypatch, "get_availability", provider)
    result = await outlook_calendar_get_availability(
        context(
            entry("work", connection_id=connection_id),
            entry("team", connection_id=connection_id),
            tool_name="outlook_calendar_get_availability",
        ),
        addresses=["dana@example.com"],
        start="2026-11-16T09:00:00",
        end="2026-11-16T11:00:00",
    )
    GET_AVAILABILITY.output_model.model_validate(result)
    assert factory.await_count == provider.post.await_count == 1
    [calendar] = result["results"]
    assert calendar["external_id"] == "work"
    assert calendar["data"]["schedules"][0]["availability_view"] == "0220"
