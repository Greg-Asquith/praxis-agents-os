# apps/api/tests/scenarios/test_outlook_send_draft_approval_resume.py

"""Outlook draft consent and durable evidence through production run resume."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from integrations.outlook_mail.references import OutlookMessageReference
from integrations.outlook_mail.tools.send_draft import DEFINITION
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
from tests.integrations.outlook_mail.support import draft_payload, entry
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("decision", ["approved", "denied", "changed"])
async def test_existing_draft_resume_preserves_reviewed_message(
    db_session_factory, monkeypatch, nested, decision
):
    definition = replace(DEFINITION, availability_check=lambda: True)
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
    payload = draft_payload("existing-draft")
    provider.get.side_effect = lambda path, **kwargs: (
        {"value": []} if path.endswith("/attachments") else payload
    )
    for factory in ("mailbox_client", "mailbox_client_for_principal"):
        monkeypatch.setattr(
            f"integrations.outlook_mail.tools.send_draft.{factory}",
            AsyncMock(return_value=provider),
        )
    reference = OutlookMessageReference(
        mailbox_id="mailbox", message_id="existing-draft", label="Existing draft"
    ).model_dump(mode="json")
    original = {"message": reference}
    context = await build_scenario_agent(
        db_session_factory, tool_names=[definition.name], code_mode_enabled=nested
    )
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {"code": f"await outlook_mail_send_draft(message={reference!r})"},
                        "workflow",
                    )
                    if nested
                    else ToolCall(definition.name, original, "draft"),
                )
            ),
            "Draft processing finished.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == "awaiting_approval"
    provider.post.assert_not_awaited()
    state = load_suspended_run_state(suspended.run)
    metadata = state.deferred_tool_requests.metadata["workflow" if nested else "draft"]
    assert metadata["display_args"]["_draft"]["body"] == "<p>Reviewed draft</p>"
    if decision == "changed":
        payload["changeKey"] = "edited-in-outlook"
        payload["body"]["content"] = "<p>Unreviewed change</p>"
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
                    tool_call_id="workflow:1" if nested else "draft",
                    decision="denied" if decision == "denied" else "approved",
                    override_args=None,
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
    if decision == "denied":
        provider.post.assert_not_awaited()
        assert operations == []
        assert any(row.status == "denied" for row in completed.audit_rows)
        return
    if decision == "changed":
        provider.post.assert_not_awaited()
        assert [row.status for row in operations] == ["failure"]
        return
    provider.post.assert_awaited_once()
    assert provider.post.await_args.args == ("/me/messages/existing-draft/send",)
    provider.patch.assert_not_awaited()
    assert sorted(row.status for row in operations) == ["pending", "success"]
    pending = next(row for row in operations if row.status == "pending")
    terminal = next(row for row in operations if row.status == "success")
    assert terminal.details["related_event_id"] == str(pending.id)
    assert terminal.details["external_ref"] == "existing-draft"
