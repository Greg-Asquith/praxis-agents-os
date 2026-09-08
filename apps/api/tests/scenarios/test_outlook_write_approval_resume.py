# apps/api/tests/scenarios/test_outlook_write_approval_resume.py

"""Outlook reply consent and durable evidence through production run resume."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from integrations.outlook_mail.references import OutlookMessageReference
from integrations.outlook_mail.tools.create_draft import DEFINITION as DRAFT_DEFINITION
from integrations.outlook_mail.tools.reply_to_message import DEFINITION
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.resume_run_stream import _build_deferred_tool_results
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME, build_run_workflow_tool
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.outlook_mail.support import entry
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.parametrize("draft_recipients", ["reply", "omitted", None, [], ["lee@example.com"]])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("approved", [False, True])
async def test_reply_resume_preserves_consent_and_durable_evidence(
    db_session_factory, monkeypatch, nested, approved, draft_recipients
):
    is_draft = draft_recipients != "reply"
    definition = replace(
        DRAFT_DEFINITION if is_draft else DEFINITION, availability_check=lambda: True
    )
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    monkeypatch.setattr(
        "services.agents.runtime.loop.build_runtime_tools",
        lambda *_args, **_kwargs: [
            build_run_workflow_tool(CodeModeCatalog.build(((definition, "approval"),)))
            if nested
            else definition.to_pydantic_tool(policy="approval")
        ],
    )
    monkeypatch.setattr(
        "services.agents.runtime.execute.setup.resolve_active_context",
        AsyncMock(return_value=ResolvedActiveContext(entries=(entry(),))),
    )
    monkeypatch.setattr(
        "services.audit_events.integration_events.get_async_db_session_factory",
        lambda: db_session_factory,
    )
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.authorize_entity_field", AsyncMock()
    )
    resolve = AsyncMock(side_effect=lambda _authorized, *, values, **_kwargs: values)
    monkeypatch.setattr(
        "services.agents.runtime.entity_references.service.resolve_authorized_references", resolve
    )
    provider = AsyncMock()
    provider.get.return_value = {"value": []}
    provider.post.return_value = {
        "id": "reply-id",
        "body": {"contentType": "html", "content": "<p>Quoted</p>"},
        "ccRecipients": [{"emailAddress": {"address": "inherited@example.com"}}],
        "bccRecipients": [{"emailAddress": {"address": "inherited-bcc@example.com"}}],
    }
    monkeypatch.setattr(
        f"integrations.outlook_mail.tools.{'create_draft' if is_draft else 'reply_to_message'}.mailbox_client",
        AsyncMock(return_value=provider),
    )
    reference = OutlookMessageReference(
        mailbox_id="mailbox", message_id="original", label="Original email"
    ).model_dump(mode="json")
    original = {
        "reply_to" if is_draft else "message": reference,
        "body_html": "<p>Proposed reply</p>",
    }
    if is_draft and draft_recipients != "omitted":
        original |= {"cc": draft_recipients, "bcc": draft_recipients}
    code_args = ", ".join(f"{key}={value!r}" for key, value in original.items())
    context = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": f"await {definition.name}({code_args})"},
                        "workflow",
                    )
                    if nested
                    else ToolCall(definition.name, original, "reply"),
                )
            ),
            "Reply processing finished.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    provider.post.assert_not_awaited()
    state = load_suspended_run_state(suspended.run)
    metadata = state.deferred_tool_requests.metadata["workflow" if nested else "reply"]
    assert metadata["display_args"]["reply_all"] is False
    if is_draft:
        expected = None if draft_recipients == "omitted" else draft_recipients
        assert metadata["display_args"]["cc"] == expected
        assert metadata["display_args"]["bcc"] == expected
        assert metadata["display_args"]["_recipient_inheritance"] == (
            ["to", "cc", "bcc"] if expected is None else ["to"]
        )
    edited = {**original, "body_html": "<p>Approved reply</p>", "reply_all": True}
    async with db_session_factory() as db:
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        deferred = await _build_deferred_tool_results(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run=run,
            suspended_state=state,
            decisions=[
                AgentRunResumeDecision(
                    tool_call_id="workflow:1" if nested else "reply",
                    decision="approved" if approved else "denied",
                    override_args=edited if approved else None,
                )
            ],
        )
    completed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status="awaiting_approval",
        message_history=state.message_history,
        deferred_tool_results=deferred,
    )
    assert completed.run.status == "completed"
    operations = [row for row in completed.audit_rows if row.details.get("provider_operation")]
    if not approved:
        provider.post.assert_not_awaited()
        assert operations == []
        assert any(row.status == "denied" for row in completed.audit_rows)
        return
    assert provider.post.await_args_list[0].args == ("/me/messages/original/createReplyAll",)
    assert (
        provider.patch.await_args.kwargs["json"]["body"]["content"]
        == "<p>Approved reply</p><p>Quoted</p>"
    )
    if is_draft:
        provider.post.assert_awaited_once()
        changes = provider.patch.await_args.kwargs["json"]
        for key in ("ccRecipients", "bccRecipients"):
            if draft_recipients is None or draft_recipients == "omitted":
                assert key not in changes
                assert provider.post.return_value[key]
            else:
                assert changes[key] == [
                    {"emailAddress": {"address": address}} for address in draft_recipients
                ]
    else:
        assert provider.post.await_args_list[-1].args == ("/me/messages/reply-id/send",)
    resolve.assert_awaited_once()
    assert sorted(row.status for row in operations) == ["pending", "success"]
    pending = next(row for row in operations if row.status == "pending")
    terminal = next(row for row in operations if row.status == "success")
    fields = pending.details["operation_detail"]["intent_groups"][0]["items"][0]["fields"]
    if is_draft:
        assert fields["to_source"] == "outlook_reply"
        assert "recipient_count" not in fields
        for key in ("cc", "bcc"):
            if draft_recipients is None or draft_recipients == "omitted":
                assert fields[f"{key}_source"] == "outlook_reply"
                assert f"{key}_count" not in fields
            else:
                assert fields[f"{key}_count"] == len(draft_recipients)
    else:
        assert fields == {"reply_all": True}
    assert terminal.details["related_event_id"] == str(pending.id)
    assert terminal.details["external_ref"] == "reply-id"
