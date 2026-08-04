# apps/api/tests/scenarios/test_approvals.py

"""Durable approval suspension, approval, and denial scenarios."""

import json
from collections.abc import AsyncIterator

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_STATUS_FAILED
from services.agents.runtime.approval_state import (
    APPROVAL_STATE_METADATA_KEY,
    load_suspended_run_state,
)
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
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


async def test_auto_mounted_artifact_tool_runs_without_agent_configuration(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)
    model = scripted_model(
        turns=[
            ToolTurn(
                (
                    ToolCall(
                        "create_artifact",
                        {
                            "title": "Quarterly summary",
                            "artifact_type": "markdown",
                            "content": "# Quarterly summary\n\nRevenue increased.",
                        },
                        "artifact-call",
                    ),
                )
            ),
            "The artifact was created.",
        ]
    )

    completed = await run_scenario(db_session_factory, context, model=model)

    assert context.agent.tool_names == []
    assert completed.run.status == "completed"
    [invocation] = completed.audit_rows
    assert invocation.tool_name == "create_artifact"
    assert invocation.details["outcome"] == "completed"


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


async def test_denial_remains_provider_valid_when_continuation_is_interrupted(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    suspended = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("scenario_external_write", {"value": "blocked"}, "deny-call"),))
            ]
        ),
    )
    state = load_suspended_run_state(suspended.run)

    async def interrupted_continuation(
        _messages,
        _info: AgentInfo,
    ) -> AsyncIterator[str]:
        if False:
            yield ""
        raise RuntimeError("continuation interrupted")

    with pytest.raises(RuntimeError, match="continuation interrupted"):
        await run_scenario(
            db_session_factory,
            context,
            model=FunctionModel(
                stream_function=interrupted_continuation,
                model_name="interrupted-denial-continuation",
            ),
            prompt=None,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={state.pending_tool_call_ids[0]: ToolDenied("User declined the action")}
            ),
        )

    next_context = await next_scenario_run(db_session_factory, context)
    continued = await run_scenario(
        db_session_factory,
        next_context,
        model=scripted_model(turns=["The previous action was denied."]),
        prompt="Continue after the denied action.",
    )

    async with db_session_factory() as db:
        stored_failed_run = await db.get(AgentRun, context.run_id)
        assert stored_failed_run is not None
        assert stored_failed_run.status == RUN_STATUS_FAILED

    denied_results = [
        part
        for message in continued.messages
        for part in message.parts.get("parts", [])
        if part.get("part_kind") == "tool-return"
        and part.get("tool_call_id") == state.pending_tool_call_ids[0]
    ]
    assert len(denied_results) == 1
    assert denied_results[0]["outcome"] == "denied"
    assert continued.run.status == "completed"
