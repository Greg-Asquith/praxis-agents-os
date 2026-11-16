# apps/api/tests/integrations/outlook_calendar/test_outlook_calendar_operations.py

"""Outlook Calendar time handling, masking, and provider content framing."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from integrations.outlook_calendar.operations.get_event import get_event
from integrations.outlook_calendar.operations.list_calendar_view import list_calendar_view
from integrations.outlook_calendar.operations.utils import PRIVATE_SUBJECT, event_summary
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.microsoft_graph.time import parse_local_datetime, validate_time_zone
from tests.integrations.outlook_calendar.support import graph_event

HOSTILE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "prompt_injection" / "hostile_email_body.txt"
).read_text(encoding="utf-8")[:400]


def test_local_times_reject_offsets_and_unknown_zones():
    with pytest.raises(ValueError, match="UTC offset"):
        parse_local_datetime("2026-11-16T09:00:00+01:00", field="start")
    with pytest.raises(ValueError, match="not a known time zone"):
        validate_time_zone("Europe/Nowhere")
    assert validate_time_zone("GMT Standard Time") == "GMT Standard Time"


async def test_calendar_view_pads_the_utc_window_and_keeps_only_local_overlaps():
    client = AsyncMock()
    client.paginate.return_value = [
        graph_event(
            "before",
            start={"dateTime": "2026-11-15T22:00:00.0000000"},
            end={"dateTime": "2026-11-15T23:00:00.0000000"},
        ),
        graph_event("inside"),
    ]
    events = await list_calendar_view(
        client,
        calendar_id="calendar",
        start=parse_local_datetime("2026-11-16T00:00:00", field="start"),
        end=parse_local_datetime("2026-11-17T00:00:00", field="end"),
        time_zone="Pacific Standard Time",
        limit=10,
        can_view_private=True,
    )
    assert [event["event_id"] for event in events] == ["inside"]
    request = client.paginate.call_args.kwargs
    assert request["params"]["startDateTime"] == "2026-11-15T10:00:00Z"
    assert request["params"]["endDateTime"] == "2026-11-17T12:00:00Z"
    assert request["headers"] == {"Prefer": 'outlook.timezone="Pacific Standard Time"'}


def test_private_subject_is_masked_without_private_item_access():
    event = event_summary(
        graph_event(sensitivity="private", location={"displayName": "Clinic"}),
        time_zone="UTC",
        can_view_private=False,
    )
    assert event["subject"] == PRIVATE_SUBJECT
    assert event["location"].content == ""
    assert event["sensitivity"] == "private"


async def test_hostile_event_content_is_only_returned_as_framed_nodes():
    hostile = HOSTILE
    client = AsyncMock()
    client.get.return_value = graph_event(
        subject=hostile,
        body={"contentType": "text", "content": hostile},
        location={"displayName": hostile},
        organizer={"emailAddress": {"name": hostile, "address": "dana@example.com"}},
        attendees=[{"emailAddress": {"name": hostile}, "type": "required"}],
    )
    event = await get_event(
        client, calendar_id="calendar", event_id="event-1", time_zone="UTC", can_view_private=True
    )

    def plain_strings(value):
        if isinstance(value, UntrustedNode):
            assert value.source_kind == "outlook_event" and value.source_ref == "event-1"
            return []
        if isinstance(value, dict):
            return [text for item in value.values() for text in plain_strings(item)]
        if isinstance(value, list):
            return [text for item in value for text in plain_strings(item)]
        assert not isinstance(value, BaseModel)
        return [value] if isinstance(value, str) else []

    assert event["body"].content == hostile
    assert not any(hostile in text for text in plain_strings(event))
