"""End-to-end AI usage ledger scenarios across terminal run paths."""

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from models.ai_usage_event import AIUsageEvent
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.run_persistence import restored_run_usage
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def _events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id,
    run_id,
) -> list[AIUsageEvent]:
    async with session_factory() as db:
        await set_session_tenant_context(db, workspace_id=workspace_id)
        return list(
            (
                await db.scalars(
                    select(AIUsageEvent)
                    .where(AIUsageEvent.run_id == run_id)
                    .order_by(AIUsageEvent.occurred_at, AIUsageEvent.created_at)
                )
            ).all()
        )


async def test_success_records_one_logical_agent_invocation(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)
    await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["Done."]),
    )

    [event] = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert event.purpose == "agent_run"
    assert event.requests == 1
    assert event.agent_id == context.agent_id
    assert event.user_id == context.user_id


async def test_approval_resume_records_non_overlapping_invocations(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}, "write"),)),
            "Approved.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    state = load_suspended_run_state(suspended.run)

    await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={state.pending_tool_call_ids[0]: ToolApproved()}
        ),
    )

    events = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert [event.requests for event in events] == [1, 1]


async def test_failed_run_records_completed_partial_request(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_bad_write"],
    )
    with pytest.raises(AssertionError, match="more requests"):
        await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(
                turns=[ToolTurn((ToolCall("scenario_bad_write", {}, "bad-write"),))]
            ),
        )

    [event] = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert event.purpose == "agent_run"
    assert event.requests == 2
    assert event.details == {"usage_source": "accumulator_delta"}


async def test_failed_approval_resume_excludes_persisted_baseline(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}, "write"),)),
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    state = load_suspended_run_state(suspended.run)

    with pytest.raises(AssertionError, match="more requests"):
        await run_scenario(
            db_session_factory,
            context,
            model=model,
            prompt=None,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={state.pending_tool_call_ids[0]: ToolApproved()}
            ),
            usage=restored_run_usage(suspended.run),
        )

    events = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert [event.requests for event in events] == [1, 1]
