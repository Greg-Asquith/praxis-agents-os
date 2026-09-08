# apps/api/tests/integrations/outlook_mail/test_write_tools.py

"""Outlook write consent, request fidelity, and terminal evidence."""

import asyncio
import importlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationTimeoutError,
)
from integrations.outlook_mail.references import OutlookMessageReference
from integrations.outlook_mail.tools import TOOL_DEFINITIONS
from services.agents.runtime.code_mode.stubs import render_tool_stub
from services.agents.runtime.tools.contract import validate_definition
from services.integrations.previews.sanitize import sanitize_preview_html
from tests.integrations.outlook_mail.support import context, entry

REFERENCE = OutlookMessageReference(
    mailbox_id="mailbox", message_id="original/==", label="Original message"
)
QUOTED = "<html><body><p>Quoted &amp; unchanged</p></body></html>"
HTML = "<p>Approved reply</p><script>unsafe()</script>"
WRITES = tuple(item for item in TOOL_DEFINITIONS if item.effect == "write")
ARGS = {
    "send_message": {"to": ["dana@example.com"], "subject": "Review", "body_html": HTML},
    "reply_to_message": {"message": REFERENCE, "body_html": HTML, "reply_all": True},
    "forward_message": {"message": REFERENCE, "to": ["kai@example.com"], "body_html": HTML},
    "create_draft": {"to": ["dana@example.com"], "subject": "Review", "body_html": HTML},
    "move_message": {"message": REFERENCE, "destination_folder": "archive"},
    "update_message": {"message": REFERENCE, "is_read": False, "flagged": True},
}


@pytest.fixture
def provider(monkeypatch):
    payload = {
        "id": "draft/==",
        "webLink": "https://outlook.office.com/mail/id/draft",
        "body": {"contentType": "html", "content": QUOTED},
    }
    client = SimpleNamespace(
        get=AsyncMock(return_value={"value": []}),
        post=AsyncMock(return_value=payload),
        patch=AsyncMock(return_value=payload),
        paginate=AsyncMock(return_value=[{"id": "folder-id", "displayName": "Invoices"}]),
    )
    factory = AsyncMock(return_value=client)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    for name in ARGS:
        monkeypatch.setattr(f"integrations.outlook_mail.tools.{name}.mailbox_client", factory)
    return SimpleNamespace(client=client, factory=factory, audit=audit)


async def invoke(name, args=None, entries=None):
    module = importlib.import_module(f"integrations.outlook_mail.tools.{name}")
    return await getattr(module, f"outlook_mail_{name}")(
        context(*(entries if entries is not None else [entry()]), tool_name=f"outlook_mail_{name}"),
        **(ARGS[name] if args is None else args),
    )


@pytest.mark.parametrize("definition", WRITES, ids=lambda item: item.name)
def test_write_contracts_show_every_argument_and_support_code_mode(definition):
    validate_definition(definition)
    assert definition.name in render_tool_stub(definition)
    assert definition.default_policy == "approval"
    assert definition.supports_approval and definition.code_eligible
    assert definition.integration_binding.requires_write
    assert definition.supports_auto == (
        definition.name in {"outlook_mail_move_message", "outlook_mail_update_message"}
    )
    schema = definition.to_pydantic_tool().function_schema.json_schema
    assert set(schema["properties"]) == {field.key for field in definition.presentation.arg_fields}
    assert all(
        field.editable == (definition.name != "outlook_mail_send_draft")
        for field in definition.presentation.arg_fields
    )


@pytest.mark.parametrize("name", ARGS)
async def test_writes_record_correlated_pending_and_terminal_evidence(provider, name):
    result = await invoke(name)
    data = result["results"][0]["data"]
    assert data["outcome"] == "applied"
    assert data["message"].message_id == "draft/=="
    assert data["web_link"].source_kind == "outlook_message"
    definition = next(item for item in WRITES if item.name == f"outlook_mail_{name}")
    definition.output_model.model_validate(result)
    assert provider.audit.await_count == 2
    pending, terminal = [call.kwargs for call in provider.audit.await_args_list]
    assert str(pending["status"]) == "pending"
    assert str(terminal["status"]) == "success"
    assert terminal["related_event_id"] == provider.audit.return_value
    assert terminal["external_ref"] == "draft/=="
    assert terminal["operation_detail"].intent_counts.applied == 1
    detail = pending["operation_detail"].model_dump_json()
    assert "Review" not in detail and "Approved reply" not in detail
    assert "connection_id" not in str(result)


@pytest.mark.parametrize("name", ARGS)
@pytest.mark.parametrize("mailboxes", [[], ["first", "second"], ["mailbox", "mailbox"]])
async def test_every_write_requires_one_mailbox_before_io(provider, name, mailboxes):
    with pytest.raises(ModelRetry, match="exactly one"):
        await invoke(name, entries=[entry(value) for value in mailboxes])
    provider.factory.assert_not_awaited()
    provider.audit.assert_not_awaited()


@pytest.mark.parametrize(
    "name", ["reply_to_message", "forward_message", "move_message", "update_message"]
)
async def test_reference_cannot_select_a_different_mailbox(provider, name):
    with pytest.raises(ModelRetry, match="belong"):
        await invoke(name, entries=[entry("other")])
    provider.factory.assert_not_awaited()


@pytest.mark.parametrize("name", ARGS)
async def test_read_only_mailbox_records_denial_without_provider_io(provider, name):
    result = await invoke(name, entries=[replace(entry(), write_allowed=False)])
    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider.factory.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"
    assert provider.audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_send_uses_exact_edited_recipients_and_sanitised_body(provider):
    args = {
        **ARGS["send_message"],
        "to": ["kai@example.com", "lee@example.com"],
        "cc": ["amal@example.com"],
        "bcc": ["alex@example.com"],
    }
    await invoke("send_message", args)
    create, send = provider.client.post.await_args_list
    assert create.args == ("/me/messages",)
    assert create.kwargs["json"] == {
        "subject": "Review",
        "body": {"contentType": "html", "content": sanitize_preview_html(HTML)},
        "toRecipients": [{"emailAddress": {"address": value}} for value in args["to"]],
        "ccRecipients": [{"emailAddress": {"address": "amal@example.com"}}],
        "bccRecipients": [{"emailAddress": {"address": "alex@example.com"}}],
    }
    assert send.args == ("/me/messages/draft%2F%3D%3D/send",)
    intent = provider.audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items[0]
    assert intent.fields == {"recipient_count": 2, "cc_count": 1, "bcc_count": 1}


@pytest.mark.parametrize(
    "name,action", [("reply_to_message", "createReplyAll"), ("forward_message", "createForward")]
)
async def test_reply_and_forward_preserve_quote_byte_for_byte(provider, name, action):
    await invoke(name)
    assert provider.client.post.await_args_list[0].args == (
        f"/me/messages/original%2F%3D%3D/{action}",
    )
    patch = provider.client.patch.await_args.kwargs["json"]
    assert patch["body"] == {"contentType": "html", "content": sanitize_preview_html(HTML) + QUOTED}
    if name == "forward_message":
        assert patch["toRecipients"] == [{"emailAddress": {"address": "kai@example.com"}}]
    assert provider.client.post.await_args_list[-1].args[0].endswith("/send")


async def test_reply_draft_does_not_send_and_retains_cc_and_bcc(provider):
    await invoke(
        "create_draft",
        {"reply_to": REFERENCE, "body_html": HTML, "cc": ["lee@example.com"], "bcc": []},
    )
    assert provider.client.post.await_count == 1
    assert provider.client.post.await_args.args[0].endswith("/createReply")
    assert provider.client.patch.await_args.kwargs["json"]["ccRecipients"] == [
        {"emailAddress": {"address": "lee@example.com"}}
    ]
    assert provider.client.patch.await_args.kwargs["json"]["bccRecipients"] == []


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"to": ["kai@example.com"]},
        {"subject": "Title"},
        {"reply_to": REFERENCE, "to": ["kai@example.com"]},
        {"reply_to": REFERENCE, "subject": "Title"},
        {"to": ["kai@example.com"], "subject": "Title", "reply_all": True},
    ],
)
async def test_invalid_draft_combinations_fail_before_io(provider, args):
    with pytest.raises(ModelRetry):
        await invoke("create_draft", args)
    provider.factory.assert_not_awaited()
    provider.audit.assert_not_awaited()


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_send_failure_retains_draft_and_records_exact_effects(provider, ambiguous):
    error = IntegrationTimeoutError if ambiguous else IntegrationPermissionError
    provider.client.post.side_effect = [
        provider.client.post.return_value,
        error(
            "Private provider body",
            failure_disposition=(
                IntegrationFailureDisposition.AMBIGUOUS
                if ambiguous
                else IntegrationFailureDisposition.REJECTED
            ),
        ),
    ]
    result = await invoke("send_message")
    data = result["results"][0]["data"]
    assert data["outcome"] == ("unverified" if ambiguous else "failed")
    assert data["error_code"] == ("unverified_mutation" if ambiguous else "send_failed")
    assert data["message"].message_id == "draft/=="
    if not ambiguous:
        assert "Check the message in Outlook" in data["detail"]
    assert "Drafts" not in data["detail"]
    assert "Private provider body" not in str(result)
    assert provider.audit.await_count == 2
    terminal = provider.audit.await_args.kwargs
    assert str(terminal["status"]) == ("unverified" if ambiguous else "failure")
    effects = terminal["operation_detail"].outcome_groups[0].outcomes[0].effects
    assert [(effect.status, effect.fields["action"]) for effect in effects] == [
        ("applied", "draft"),
        ("unverified" if ambiguous else "failed", "send"),
    ]


async def test_cancelled_send_closes_terminal_evidence_and_propagates(provider):
    cancelled = asyncio.CancelledError()
    cancelled.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
    provider.client.post.side_effect = [provider.client.post.return_value, cancelled]
    with pytest.raises(asyncio.CancelledError) as raised:
        await invoke("send_message")
    assert raised.value.operation_detail.effect_counts.applied == 1
    assert raised.value.operation_detail.effect_counts.unverified == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "unverified"


async def test_unknown_folder_fails_before_pending_or_mutation(provider):
    result = await invoke("move_message", {"message": REFERENCE, "destination_folder": "Unknown"})
    assert result["results"][0]["error_code"] == "folder_not_found"
    provider.client.post.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"


async def test_display_name_folder_resolves_before_pending(provider):
    await invoke("move_message", {"message": REFERENCE, "destination_folder": "Invoices"})
    assert provider.client.post.await_args.kwargs["json"] == {"destinationId": "folder-id"}
    intent = provider.audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items[0]
    assert intent.fields == {"destination_folder": "Invoices"}


async def test_update_preserves_false_and_requires_one_strict_boolean(provider):
    await invoke("update_message")
    assert provider.client.patch.await_args.kwargs["json"] == {
        "isRead": False,
        "flag": {"flagStatus": "flagged"},
    }
    for changes in ({}, {"is_read": "false"}, {"flagged": 1}):
        with pytest.raises(ModelRetry):
            await invoke("update_message", {"message": REFERENCE, **changes})


@pytest.mark.parametrize("nested", [False, True])
async def test_approval_defaults_preserve_direct_and_nested_replay_args(nested):
    from pydantic_ai import DeferredToolRequests
    from pydantic_ai.messages import ToolCallPart

    from services.agents.runtime.approval_events import add_approval_display_args
    from services.agents.runtime.code_mode.approval import build_code_mode_approval_metadata

    original = {"message": REFERENCE.model_dump(mode="json"), "body_html": "<p>Reply</p>"}
    call = ToolCallPart("outlook_mail_reply_to_message", original, tool_call_id="reply")
    outer = ToolCallPart("run_code", {"code": "reply()"}, tool_call_id="outer")
    metadata = (
        build_code_mode_approval_metadata(outer_tool_call_id="outer", nested_call=call, reason=None)
        if nested
        else {}
    )
    request = DeferredToolRequests(
        approvals=[outer if nested else call], metadata={"outer" if nested else "reply": metadata}
    )
    result = await add_approval_display_args(
        SimpleNamespace(workspace_tool_definitions=()), request
    )
    display = result.metadata["outer" if nested else "reply"]["display_args"]
    assert display["reply_all"] is False
    assert original == {"message": REFERENCE.model_dump(mode="json"), "body_html": "<p>Reply</p>"}
    assert result.approvals == request.approvals


async def test_approved_reply_all_edit_reaches_executed_graph_request(provider, monkeypatch):
    from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args

    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field", AsyncMock()
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references",
        AsyncMock(return_value=[REFERENCE.model_dump(mode="json")]),
    )
    original = {"message": REFERENCE.model_dump(mode="json"), "body_html": HTML}
    args = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=SimpleNamespace(tool_name="outlook_mail_reply_to_message", args=original),
        override_args={**original, "reply_all": True},
    )
    await invoke("reply_to_message", args)
    assert provider.client.post.await_args_list[0].args[0].endswith("/createReplyAll")
    assert provider.audit.await_args_list[0].kwargs["operation_detail"].intent_groups[0].items[
        0
    ].fields == {"reply_all": True}


async def test_new_draft_secondary_null_survives_server_edit_validation(provider):
    from services.agent_runs.validate_override_args import validate_and_canonicalize_override_args

    original = {**ARGS["create_draft"], "reply_to": None}
    args = await validate_and_canonicalize_override_args(
        AsyncMock(),
        actor=SimpleNamespace(),
        workspace=SimpleNamespace(),
        membership=SimpleNamespace(),
        run=SimpleNamespace(conversation_id=uuid4()),
        tool_call=SimpleNamespace(tool_name="outlook_mail_create_draft", args=original),
        override_args={**original, "subject": "Edited subject"},
    )
    assert args["reply_to"] is None
    await invoke("create_draft", args)
    assert provider.client.post.await_args.kwargs["json"]["subject"] == "Edited subject"


@pytest.mark.parametrize(
    "body",
    [None, {"contentType": "text", "content": "Quoted"}, {"contentType": "html", "content": ""}],
)
async def test_missing_html_quote_leaves_draft_and_never_sends(provider, body):
    provider.client.post.return_value = {**provider.client.post.return_value, "body": body}
    result = await invoke("reply_to_message")
    assert result["results"][0]["data"]["outcome"] == "failed"
    assert result["results"][0]["data"]["error_code"] == "quoted_conversation_unavailable"
    provider.client.patch.assert_not_awaited()
    assert provider.client.post.await_count == 1


@pytest.mark.parametrize("error", [TimeoutError("Private detail"), RuntimeError("Private detail")])
async def test_untyped_failure_after_draft_is_unverified(provider, error):
    provider.client.post.side_effect = [provider.client.post.return_value, error]
    result = await invoke("send_message")
    assert result["results"][0]["data"]["outcome"] == "unverified"
    assert "Private detail" not in str(result)
    assert provider.audit.await_args.kwargs["operation_detail"].effect_counts.unverified == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"to": []},
        {"to": ["kai@example.com"] * 101},
        {"cc": ["not-an-address"]},
        {"bcc": ["kai@example.com\x00"]},
        {"to": ["Kai <kai@example.com>"]},
        {"to": ["kai@example.com\r\nBcc: lee@example.com"]},
        {"subject": "x" * 999},
        {"subject": "Bad\nSubject"},
        {"body_html": "x" * 50_001},
        {"body_html": "\ud800"},
        {"reply_all": "false"},
    ],
)
async def test_invalid_write_arguments_fail_before_provider_or_audit(provider, changes):
    from pydantic import ValidationError

    from integrations.outlook_mail.tools.mutations import DraftInput

    with pytest.raises(ValidationError):
        DraftInput.model_validate({**ARGS["create_draft"], **changes})
    with pytest.raises(ModelRetry):
        await invoke("create_draft", {**ARGS["create_draft"], **changes})
    provider.factory.assert_not_awaited()
    provider.audit.assert_not_awaited()


@pytest.mark.parametrize("name", ARGS)
async def test_graph_wire_requests_retain_immutable_ids_and_no_send_mail_shortcut(provider, name):
    import httpx2

    from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token

    requests = []

    def handler(request):
        requests.append(request)
        assert 'IdType="ImmutableId"' in request.headers["Prefer"]
        assert request.headers["Authorization"] == "Bearer test-token"
        assert "sendMail" not in request.url.path
        if request.url.path.endswith("/attachments"):
            return httpx2.Response(200, json={"value": []})
        if request.url.path.endswith("/send"):
            return httpx2.Response(202)
        return httpx2.Response(
            201 if request.method == "POST" else 200, json=provider.client.post.return_value
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        provider.factory.return_value = MicrosoftGraphClient(
            fixed_access_token("test-token"), provider_key="outlook_mail", client=transport
        )
        result = await invoke(name)
    assert result["results"][0]["data"]["outcome"] == "applied"
    assert (
        len(requests)
        == {
            "send_message": 2,
            "reply_to_message": 4,
            "forward_message": 4,
            "create_draft": 1,
            "move_message": 1,
            "update_message": 1,
        }[name]
    )
    assert provider.audit.await_args.kwargs["http_requests"] == len(requests)
    assert provider.audit.await_args.kwargs["http_attempts"] == len(requests)


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("invalid_field", ["draft_kind", "subject", "to"])
async def test_invalid_approval_projection_keeps_private_values_out_of_logs(
    provider, caplog, nested, invalid_field
):
    from pydantic_ai import DeferredToolRequests
    from pydantic_ai.messages import ToolCallPart

    from services.agents.runtime.approval_events import add_approval_display_args
    from services.agents.runtime.code_mode.approval import build_code_mode_approval_metadata

    markers = ["PRIVATE_BODY_SENTINEL", "PRIVATE_SUBJECT_SENTINEL", "PRIVATE_RECIPIENT_SENTINEL"]
    original = {
        "body_html": markers[0],
        "subject": markers[1],
        "to": [f"{markers[2]}@example.com"],
    }
    if invalid_field == "draft_kind":
        original["reply_all"] = True
    elif invalid_field == "subject":
        original["subject"] += "\n"
    else:
        original["to"] = [markers[2]]
    call = ToolCallPart("outlook_mail_create_draft", original, tool_call_id="draft")
    outer = ToolCallPart("run_code", {"code": "draft()"}, tool_call_id="outer")
    call_id = "outer" if nested else "draft"
    metadata = (
        build_code_mode_approval_metadata(outer_tool_call_id="outer", nested_call=call, reason=None)
        if nested
        else {}
    )
    requests = DeferredToolRequests(
        approvals=[outer if nested else call], metadata={call_id: metadata}
    )
    result = await add_approval_display_args(
        SimpleNamespace(workspace_tool_definitions=()), requests
    )
    display = result.metadata[call_id]["display_args"]
    assert display["_approval_display_error"]
    assert display["body_html"] == original["body_html"]
    assert "Approval display argument projection failed" in caplog.text
    for marker in markers:
        assert marker not in caplog.text
        assert marker not in display["_approval_display_error"]
    provider.factory.assert_not_awaited()
    provider.client.post.assert_not_awaited()
    provider.client.patch.assert_not_awaited()


@pytest.mark.parametrize("name", ["forward_message", "reply_to_message"])
@pytest.mark.parametrize(
    "attachments",
    [
        {"value": [{"id": "ordinary", "isInline": False}]},
        {"value": [{"id": "inline", "isInline": True}]},
        {},
        None,
        [],
        {"value": None},
        {"value": {}},
        {"value": [], "@odata.nextLink": "more"},
        {"value": [], "@odata.nextLink": None},
        {"value": [], "@odata.nextLink": False},
    ],
)
async def test_generated_draft_attachment_rejection_preserves_effects(provider, name, attachments):
    provider.client.get.return_value = attachments
    result = await invoke(name)
    data = result["results"][0]["data"]
    assert data["outcome"] == "failed"
    assert data["error_code"] == "draft_attachments_unsupported"
    assert data["message"].message_id == "draft/=="
    assert "Check the message in Outlook" in data["detail"]
    provider.client.post.assert_awaited_once()
    provider.client.get.assert_awaited_once()
    assert provider.client.get.await_args.args == ("/me/messages/draft%2F%3D%3D/attachments",)
    patch = provider.client.patch.await_args.kwargs["json"]
    assert patch["body"]["content"] == sanitize_preview_html(HTML) + QUOTED
    assert "attachments" not in patch
    pending, terminal = [call.kwargs for call in provider.audit.await_args_list]
    assert str(pending["status"]) == "pending"
    assert str(terminal["status"]) == "failure"
    assert terminal["related_event_id"] == provider.audit.return_value
    assert terminal["external_ref"] == "draft/=="
    effects = terminal["operation_detail"].outcome_groups[0].outcomes[0].effects
    assert [(effect.status, effect.fields["action"]) for effect in effects] == [
        ("applied", "draft"),
        ("applied", "patch"),
        ("failed", "check_attachments"),
    ]


@pytest.mark.parametrize("name", ["forward_message", "reply_to_message"])
async def test_generated_draft_guard_does_not_limit_quote_to_saved_review_bound(provider, name):
    quoted = "<p>" + "Quoted " * 10_000 + "</p>"
    provider.client.post.return_value["body"]["content"] = quoted
    await invoke(name)
    assert provider.client.patch.await_args.kwargs["json"]["body"]["content"] == (
        sanitize_preview_html(HTML) + quoted
    )
    assert provider.client.post.await_args_list[-1].args[0].endswith("/send")
