# apps/api/tests/integrations/outlook_calendar/support.py

"""Shared Outlook calendar entries and run context fixtures."""

from types import SimpleNamespace
from uuid import uuid4

from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def entry(calendar_id="calendar", *, connection_id=None, can_view_private=True):
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="outlook_calendar",
        resource_type="outlook_calendar",
        external_id=calendar_id,
        display_name=f"{calendar_id} calendar",
        connection_id=connection_id or uuid4(),
        connection_label="Outlook Calendar",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={
            "time_zone": "GMT Standard Time",
            "can_view_private_items": can_view_private,
        },
    )


def context(*entries, tool_name):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            db=object(),
            user=object(),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Calendar agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="call-1",
    )


def graph_event(event_id="event-1", **values):
    return {
        "id": event_id,
        "subject": "Planning",
        "start": {"dateTime": "2026-11-16T09:00:00.0000000", "timeZone": "GMT Standard Time"},
        "end": {"dateTime": "2026-11-16T10:00:00.0000000", "timeZone": "GMT Standard Time"},
        "sensitivity": "normal",
        **values,
    }
