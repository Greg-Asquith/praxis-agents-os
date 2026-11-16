# apps/api/tests/integrations/outlook_calendar/test_outlook_calendar_write_tools.py

"""Outlook Calendar write consent, approved values, idempotency, and evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationTimeoutError
from integrations.outlook_calendar.references import OutlookEventReference
from integrations.outlook_calendar.tools.cancel_event import outlook_calendar_cancel_event
from integrations.outlook_calendar.tools.create_event import (
    DEFINITION as CREATE_EVENT,
    outlook_calendar_create_event,
)
from integrations.outlook_calendar.tools.update_event import outlook_calendar_update_event
from integrations.outlook_calendar.tools.utils import transaction_id
from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args
from tests.integrations.outlook_calendar.support import context, entry

ARGS = {
    "subject": "Quarterly plan",
    "start": "2026-11-18T09:00:00",
    "end": "2026-11-18T10:00:00",
    "attendees": ["dana@example.com"],
    "body_html": "<p>Agenda</p>",
}
EVENT = OutlookEventReference(calendar_id="calendar", event_id="event/==", label="Outlook event")


@pytest.fixture
def provider(monkeypatch):
    client = SimpleNamespace(
        get=AsyncMock(),
        post=AsyncMock(return_value={"id": "event/==", "webLink": "https://outlook.office.com/x"}),
        patch=AsyncMock(return_value={}),
        delete=AsyncMock(),
    )
    factory = AsyncMock(return_value=client)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    for name in ("create_event", "update_event", "cancel_event"):
        monkeypatch.setattr(f"integrations.outlook_calendar.tools.{name}.calendar_client", factory)
    return SimpleNamespace(client=client, factory=factory, audit=audit)


def _approve(monkeypatch, ctx, args):
    """Records the display the approver saw, as the approval runtime does."""
    display = CREATE_EVENT.approval_display_args(ctx.deps, args)
    monkeypatch.setattr(
        "integrations.outlook_calendar.tools.utils.approved_display_args", lambda _ctx: display
    )
    return display


async def test_create_without_approved_details_performs_no_provider_io(provider):
    ctx = context(entry(), tool_name="outlook_calendar_create_event")
    ctx.tool_call_approved = False
    with pytest.raises(ModelRetry, match="approved details are unavailable"):
        await outlook_calendar_create_event(ctx, **ARGS)
    provider.factory.assert_not_awaited()
    provider.audit.assert_not_awaited()


async def test_create_sends_the_edited_values_and_the_zone_the_approver_saw(provider, monkeypatch):
    ctx = context(entry(), tool_name="outlook_calendar_create_event")
    display = _approve(monkeypatch, ctx, ARGS)
    assert display["time_zone"] == "GMT Standard Time"
    edited = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=SimpleNamespace(tool_name="outlook_calendar_create_event", args=ARGS),
        override_args={
            **ARGS,
            "start": "2026-11-18T14:30",
            "end": "2026-11-18T15:00",
            "attendees": ["kai@example.com", "lee@example.com"],
        },
    )

    result = await outlook_calendar_create_event(ctx, **edited)

    request = provider.client.post.await_args
    assert request.args == ("/me/calendars/calendar/events",)
    sent = request.kwargs["json"]
    assert sent["start"] == {"dateTime": "2026-11-18T14:30:00", "timeZone": "GMT Standard Time"}
    assert [item["emailAddress"]["address"] for item in sent["attendees"]] == [
        "kai@example.com",
        "lee@example.com",
    ]
    assert sent["transactionId"] == transaction_id(ctx)
    pending = provider.audit.await_args_list[0].kwargs["operation_detail"]
    assert pending.intent_groups[0].items[0].fields["transaction_id"] == sent["transactionId"]
    recorded = pending.model_dump_json()
    assert all(value not in recorded for value in ("Quarterly plan", "Agenda", "kai@example.com"))
    data = result["results"][0]["data"]
    assert data["outcome"] == "applied"
    assert data["event"].event_id == "event/=="
    CREATE_EVENT.output_model.model_validate(result)


async def test_a_rerun_of_one_approved_call_reuses_its_transaction_id():
    run = uuid4()
    first = context(entry(), tool_name="outlook_calendar_create_event")
    again = context(entry(), tool_name="outlook_calendar_create_event")
    other = context(entry(), tool_name="outlook_calendar_create_event")
    first.deps.run.id = again.deps.run.id = other.deps.run.id = run
    other.tool_call_id = "call-2"
    assert transaction_id(first) == transaction_id(again) != transaction_id(other)


async def test_a_timeout_after_dispatch_records_unverified(provider, monkeypatch):
    provider.client.post.side_effect = IntegrationTimeoutError(
        "Private detail", failure_disposition=IntegrationFailureDisposition.AMBIGUOUS
    )
    ctx = context(entry(), tool_name="outlook_calendar_create_event")
    _approve(monkeypatch, ctx, ARGS)

    result = await outlook_calendar_create_event(ctx, **ARGS)

    assert result["results"][0]["data"]["outcome"] == "unverified"
    assert "Private detail" not in str(result)
    assert str(provider.audit.await_args.kwargs["status"]) == "unverified"


async def test_create_with_two_non_default_calendars_asks_which_before_approval():
    ctx = context(entry("Work"), entry("Family"), tool_name="outlook_calendar_create_event")
    with pytest.raises(ModelRetry, match="Work calendar, Family calendar"):
        CREATE_EVENT.args_validator(ctx, **ARGS)


async def test_update_patches_only_the_fields_it_was_given(provider):
    provider.client.get.return_value = {
        "isOrganizer": True,
        "attendees": [{}],
        "type": "occurrence",
    }

    result = await outlook_calendar_update_event(
        context(entry(), tool_name="outlook_calendar_update_event"), event=EVENT, subject="Moved"
    )

    request = provider.client.patch.await_args
    assert request.args == ("/me/calendars/calendar/events/event%2F%3D%3D",)
    assert request.kwargs["json"] == {"subject": "Moved"}
    assert result["results"][0]["data"]["event_type"] == "occurrence"


@pytest.mark.parametrize(
    ("is_organizer", "posted"),
    [(True, "/me/calendars/calendar/events/event%2F%3D%3D/cancel"), (False, None)],
)
async def test_cancel_sends_a_cancellation_only_for_the_organiser(provider, is_organizer, posted):
    provider.client.get.return_value = {
        "isOrganizer": is_organizer,
        "attendees": [{"emailAddress": {"address": "dana@example.com"}}],
        "type": "singleInstance",
    }
    result = await outlook_calendar_cancel_event(
        context(entry(), tool_name="outlook_calendar_cancel_event"), event=EVENT, comment="Sorry"
    )
    data = result["results"][0]["data"]
    if posted:
        assert provider.client.post.await_args.args == (posted,)
        assert provider.client.post.await_args.kwargs["json"] == {"comment": "Sorry"}
        assert data["action"] == "cancelled"
    else:
        provider.client.post.assert_not_awaited()
        provider.client.delete.assert_not_awaited()
        assert data["outcome"] == "failed"
        assert data["error_code"] == "not_organizer"
