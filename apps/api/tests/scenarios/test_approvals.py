# apps/api/tests/scenarios/test_approvals.py

"""Durable approval suspension, approval, and denial scenarios."""

import json

from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import (
    APPROVAL_STATE_METADATA_KEY,
    load_suspended_run_state,
)
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_approval_suspend_then_override_args_and_execute(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_external_write", {"value": ""}, "approval-call"),)),
            "The approved write completed.",
        ]
    )

    suspended = await run_scenario(db_session_factory, context, model=model)

    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    assert APPROVAL_STATE_METADATA_KEY in suspended.run.metadata_json
    [pending] = suspended.audit_rows
    assert pending.details["outcome"] == "approval_requested"
    state = load_suspended_run_state(suspended.run)

    resumed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={
                state.pending_tool_call_ids[0]: ToolApproved(override_args={"value": "approved"})
            }
        ),
    )

    assert resumed.run.status == "completed"
    assert APPROVAL_STATE_METADATA_KEY not in (resumed.run.metadata_json or {})
    assert {row.details["outcome"] for row in resumed.audit_rows} == {
        "approval_requested",
        "completed",
    }
    persisted = json.dumps([message.parts for message in resumed.messages])
    assert '"ok": true' in persisted
    assert resumed.output == "The approved write completed."


async def test_approval_denial_is_audited_and_visible_in_persisted_history(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_external_write", {"value": "blocked"}, "deny-call"),)),
            "The user denied the write, so I did not perform it.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    state = load_suspended_run_state(suspended.run)

    resumed = await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={state.pending_tool_call_ids[0]: ToolDenied("User declined the action")}
        ),
    )

    assert resumed.run.status == "completed"
    assert {row.details["outcome"] for row in resumed.audit_rows} == {
        "approval_requested",
        "denied_approval",
    }
    persisted = json.dumps([message.parts for message in resumed.messages])
    assert "User declined the action" in persisted
    assert resumed.output == "The user denied the write, so I did not perform it."
