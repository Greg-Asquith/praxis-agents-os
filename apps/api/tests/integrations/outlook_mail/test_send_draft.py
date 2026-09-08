# apps/api/tests/integrations/outlook_mail/test_send_draft.py

"""Existing-draft sending preserves identity and checks retained approval evidence."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests, ModelRetry
from pydantic_ai.messages import ToolCallPart

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from integrations.outlook_mail.operations.read_draft import DraftSnapshot, read_draft
from integrations.outlook_mail.references import OutlookMessageReference
from integrations.outlook_mail.tools.send_draft import draft_display_args, outlook_mail_send_draft
from services.agents.runtime.approval_state import build_suspended_run_metadata
from services.agents.runtime.code_mode.approval import build_code_mode_approval_metadata
from services.integrations.approved_display_args import approved_display_args
from tests.integrations.outlook_mail.support import context, draft_payload, entry

REFERENCE = OutlookMessageReference(
    mailbox_id="mailbox", message_id="draft/==", label="Draft to send"
)


@pytest.fixture
def draft_context(monkeypatch):
    ctx = context(entry(), tool_name="outlook_mail_send_draft")
    ctx.tool_call_approved = True
    ctx.deps.run.metadata_json = None
    ctx.deps.run.conversation_id = uuid4()
    ctx.deps.run.agent_id = ctx.deps.agent.id
    payload = draft_payload()
    call = ToolCallPart(ctx.tool_name, {"message": REFERENCE.model_dump()}, ctx.tool_call_id)
    requests = DeferredToolRequests(
        approvals=[call],
        metadata={
            call.tool_call_id: {
                "display_args": {
                    "message": REFERENCE.model_dump(),
                    "_draft": DraftSnapshot.model_validate(payload).approval_details(),
                }
            }
        },
    )
    ctx.deps.run.metadata_json = build_suspended_run_metadata(
        run=ctx.deps.run,
        conversation=SimpleNamespace(id=ctx.deps.run.conversation_id),
        message_history=[],
        deferred_tool_requests=requests,
    )
    client = AsyncMock()
    client.get.side_effect = lambda path, **kwargs: (
        {"value": []} if path.endswith("/attachments") else payload
    )
    audit = AsyncMock(return_value=uuid4())
    factory = AsyncMock(return_value=client)
    monkeypatch.setattr("integrations.outlook_mail.tools.send_draft.mailbox_client", factory)
    monkeypatch.setattr(
        "integrations.outlook_mail.tools.send_draft.mailbox_client_for_principal", factory
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    return SimpleNamespace(ctx=ctx, client=client, payload=payload, audit=audit, factory=factory)


async def test_send_uses_existing_id_without_creating_or_patching(draft_context):
    fixture = draft_context
    result = await outlook_mail_send_draft(fixture.ctx, REFERENCE)
    fixture.client.post.assert_awaited_once()
    assert fixture.client.post.await_args.args == ("/me/messages/draft%2F%3D%3D/send",)
    assert "json" not in fixture.client.post.await_args.kwargs
    fixture.client.patch.assert_not_awaited()
    assert result["results"][0]["data"]["message"].message_id == REFERENCE.message_id
    assert [str(call.kwargs["status"]) for call in fixture.audit.await_args_list] == [
        "pending",
        "success",
    ]
    assert fixture.audit.await_args.kwargs["external_ref"] == REFERENCE.message_id


async def test_json_created_draft_can_use_default_mailbox_sender(draft_context):
    fixture = draft_context
    del fixture.payload["from"]
    del fixture.payload["sender"]
    display = await draft_display_args(fixture.ctx.deps, {"message": REFERENCE.model_dump()})
    assert display["_draft"]["from"] == "Selected mailbox"
    metadata = fixture.ctx.deps.run.metadata_json["approval_state"]["deferred_tool_requests"][
        "metadata"
    ]
    metadata[fixture.ctx.tool_call_id]["display_args"] = display
    await outlook_mail_send_draft(fixture.ctx, REFERENCE)
    fixture.client.post.assert_awaited_once()


@pytest.mark.parametrize("field", ["changeKey", "subject", "body", "bccRecipients", "isDraft"])
async def test_changed_or_sent_draft_is_not_sent(draft_context, field):
    fixture = draft_context
    replacements = {
        "changeKey": "version-2",
        "subject": "Changed subject",
        "body": {"contentType": "html", "content": "Changed content"},
        "bccRecipients": [{"emailAddress": {"address": "kai@example.com"}}],
        "isDraft": False,
    }
    fixture.payload[field] = replacements[field]
    await outlook_mail_send_draft(fixture.ctx, REFERENCE)
    fixture.client.post.assert_not_awaited()
    assert [str(call.kwargs["status"]) for call in fixture.audit.await_args_list] == ["failure"]


@pytest.mark.parametrize("nested", [False, True])
def test_approved_evidence_is_bound_to_call_and_run(draft_context, nested):
    ctx = draft_context.ctx
    snapshot = ctx.deps.run.metadata_json["approval_state"]
    if nested:
        requests = snapshot["deferred_tool_requests"]
        call = ToolCallPart(ctx.tool_name, {"message": REFERENCE.model_dump()}, ctx.tool_call_id)
        metadata = build_code_mode_approval_metadata(
            outer_tool_call_id="workflow", nested_call=call, reason=None
        )
        metadata["display_args"] = requests["metadata"][ctx.tool_call_id]["display_args"]
        requests["approvals"] = [
            {"tool_name": "run_workflow", "args": {"code": "pass"}, "tool_call_id": "workflow"}
        ]
        requests["metadata"] = {"workflow": metadata}
        snapshot["pending_tool_call_ids"] = ["workflow"]
    assert approved_display_args(ctx)["_draft"]["subject"] == "Draft to send"
    ctx.tool_call_id = "another-call"
    with pytest.raises(ModelRetry):
        approved_display_args(ctx)


async def test_unapproved_call_and_substituted_reference_cannot_send(draft_context):
    fixture = draft_context
    fixture.ctx.tool_call_approved = False
    with pytest.raises(ModelRetry):
        await outlook_mail_send_draft(fixture.ctx, REFERENCE)
    fixture.ctx.tool_call_approved = True
    with pytest.raises(ModelRetry):
        await outlook_mail_send_draft(
            fixture.ctx, REFERENCE.model_copy(update={"message_id": "another-draft"})
        )
    fixture.factory.assert_not_awaited()


async def test_read_only_mailbox_cannot_prepare_or_send(draft_context):
    fixture = draft_context
    fixture.ctx.deps.active_context = replace(
        fixture.ctx.deps.active_context, entries=(replace(entry(), write_allowed=False),)
    )
    with pytest.raises(ModelRetry):
        await draft_display_args(fixture.ctx.deps, {"message": REFERENCE.model_dump()})
    result = await outlook_mail_send_draft(fixture.ctx, REFERENCE)
    assert result["results"][0]["error_code"] == "write_not_permitted"
    fixture.factory.assert_not_awaited()


@pytest.mark.parametrize(
    "attachments", [{"value": [{"id": "inline"}]}, {}, {"value": [], "@odata.nextLink": "more"}]
)
async def test_attachments_and_incomplete_collection_fail_closed(draft_context, attachments):
    client = draft_context.client
    client.get.side_effect = [draft_context.payload, attachments]
    with pytest.raises(IntegrationValidationError, match="attachments"):
        await read_draft(client, message_id=REFERENCE.message_id)
    client.post.assert_not_awaited()


async def test_approval_contains_all_recipients_and_sanitised_body(draft_context):
    fixture = draft_context
    fixture.payload["body"]["content"] = "<p>Review</p><script>unsafe()</script>"
    fixture.payload["bccRecipients"] = deepcopy(fixture.payload["toRecipients"])
    result = await draft_display_args(fixture.ctx.deps, {"message": REFERENCE.model_dump()})
    assert result["_draft"]["bcc"] == ["dana@example.com"]
    assert result["_draft"]["body"] == "<p>Review</p>"
    assert "script" in fixture.payload["body"]["content"]
    fixture.client.post.assert_not_awaited()


@pytest.mark.parametrize(
    "error_type", [IntegrationPermissionError, IntegrationNotFoundError, IntegrationTimeoutError]
)
async def test_failed_send_retains_existing_reference_without_retry(draft_context, error_type):
    ambiguous = error_type is IntegrationTimeoutError
    fixture = draft_context
    fixture.client.post.side_effect = (
        IntegrationTimeoutError(
            "Timed out", failure_disposition=IntegrationFailureDisposition.AMBIGUOUS
        )
        if ambiguous
        else error_type("Rejected", failure_disposition=IntegrationFailureDisposition.REJECTED)
    )
    result = await outlook_mail_send_draft(fixture.ctx, REFERENCE)
    fixture.client.post.assert_awaited_once()
    assert fixture.audit.await_args.kwargs["external_ref"] == REFERENCE.message_id
    assert str(fixture.audit.await_args.kwargs["status"]) == (
        "unverified" if ambiguous else "failure"
    )
    assert result["results"][0]["data"]["message"].message_id == REFERENCE.message_id

    data = result["results"][0]["data"]
    assert data["error_code"] == ("unverified_mutation" if ambiguous else "send_failed")
    assert "Check the message" in data["detail"]
    assert "Drafts" not in data["detail"]
    assert "Nothing was sent" not in data["detail"]
    pending, terminal = [call.kwargs for call in fixture.audit.await_args_list]
    assert str(pending["status"]) == "pending"
    assert terminal["related_event_id"] == fixture.audit.return_value
