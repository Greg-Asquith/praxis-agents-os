# apps/api/tests/services/agent_schedules/test_agent_runner.py

"""Worker-level tests for the scheduled agent runner."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import workers.agent_runner as agent_runner
from core.database import (
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
)
from core.settings import settings
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_schedules.runs import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_TERMINAL_FAILED,
    claim_due_schedule_runs,
)
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.sinks import NullSink
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from services.agents.runtime.worker import run_resume_worker
from tests.factories import build_user, build_workspace, build_workspace_membership
from workers.agent_runner import run_once

pytestmark = pytest.mark.asyncio


async def _create_due_schedule(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tool_names: list[str] | None = None,
    tool_policies: dict[str, str] | None = None,
    execution_params: dict[str, object] | None = None,
):
    async with session_factory() as db:
        now = datetime.now(UTC)
        user = build_user(email=f"worker-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"worker-{uuid4().hex[:8]}")
        membership = build_workspace_membership(
            workspace_id=workspace.id,
            user_id=user.id,
        )
        db.add_all([user, workspace, membership])
        await db.flush()

        agent = Agent(
            name="Worker Agent",
            slug=f"worker-agent-{uuid4().hex[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider="openai",
            model="gpt-6-luna",
            tool_names=tool_names or [],
            tool_policies=tool_policies,
        )
        db.add(agent)
        await db.flush()

        schedule = AgentSchedule(
            agent_id=agent.id,
            user_id=user.id,
            workspace_id=workspace.id,
            schedule_type="once",
            run_once_at=now - timedelta(minutes=1),
            next_run_at=now - timedelta(minutes=1),
            default_prompt="Run the scheduled worker task",
            execution_params=execution_params,
        )
        db.add(schedule)
        await db.flush()
        schedule_id = schedule.id
        await db.commit()
        return schedule_id


async def _set_schedule_tenant_context(db: AsyncSession, schedule_id: UUID) -> None:
    """Resolve test tenant data explicitly before opening an RLS-scoped view."""
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        workspace_id, user_id = (
            await maintenance_db.execute(
                select(AgentSchedule.workspace_id, AgentSchedule.user_id).where(
                    AgentSchedule.id == schedule_id
                )
            )
        ).one()
    await set_session_tenant_context(db, workspace_id=workspace_id, user_id=user_id)


async def test_schedule_deadline_stops_provider_wait_and_releases_worker(
    committed_db_session_factory,
    monkeypatch,
):
    schedule_id = await _create_due_schedule(committed_db_session_factory)
    unrelated_schedule_id = await _create_due_schedule(committed_db_session_factory)

    async def claim_test_schedule() -> UUID | None:
        async with committed_db_session_factory() as db:
            await _set_schedule_tenant_context(db, schedule_id)
            claimed = await claim_due_schedule_runs(db, batch_size=1)
            await db.commit()
            return claimed[0].run.id if claimed else None

    monkeypatch.setattr(agent_runner, "_claim_one_schedule_run", claim_test_schedule)
    monkeypatch.setattr(settings, "AGENT_RUN_MAX_DURATION_SECONDS", 1)
    monkeypatch.setattr(settings, "AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    stopped = asyncio.Event()

    async def provider_wait(_messages, _info):
        try:
            await asyncio.Event().wait()
            yield "Unreachable"
        finally:
            stopped.set()

    await asyncio.wait_for(
        run_once(
            owner_instance_id="test-worker",
            model=FunctionModel(stream_function=provider_wait),
        ),
        timeout=5,
    )
    assert stopped.is_set()
    async with committed_db_session_factory() as db:
        await _set_schedule_tenant_context(db, schedule_id)
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(
                AgentScheduleRun.schedule_id == schedule_id,
            )
        )
        assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
        run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert run.status == "failed" and run.error_code == "run_duration_expired"
    assert await run_once(owner_instance_id="test-worker") == 0
    async with committed_db_session_factory() as db:
        await _set_schedule_tenant_context(db, unrelated_schedule_id)
        assert (
            await db.scalar(
                select(AgentScheduleRun.id).where(
                    AgentScheduleRun.schedule_id == unrelated_schedule_id
                )
            )
            is None
        )
        unrelated_schedule = await db.get(AgentSchedule, unrelated_schedule_id)
        unrelated_schedule.is_active = False
        unrelated_schedule.next_run_at = None
        await db.commit()


@pytest.fixture
def scheduled_external_write_tool():
    tool_name = "scheduled_external_write"
    RUNTIME_TOOL_CATALOG.pop(tool_name, None)
    executions = {"count": 0}

    @runtime_tool(
        name=tool_name,
        provider="test",
        label="Scheduled external write",
        description="Perform an external write for scheduled worker tests.",
        effect=TOOL_EFFECT_WRITE,
        effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        egress=TOOL_EGRESS_EXTERNAL_WRITE,
    )
    async def scheduled_external_write(value: str) -> dict[str, bool]:
        executions["count"] += 1
        return {"ok": bool(value)}

    yield executions
    RUNTIME_TOOL_CATALOG.pop(tool_name, None)


def _scheduled_external_write_model() -> FunctionModel:
    async def stream_external_write(
        messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if not any(
            getattr(part, "part_kind", None) == "tool-return"
            and getattr(part, "tool_name", None) == "scheduled_external_write"
            for message in messages
            for part in getattr(message, "parts", [])
        ):
            yield {
                0: DeltaToolCall(
                    name="scheduled_external_write",
                    json_args=json.dumps({"value": "scheduled mutation"}),
                    tool_call_id="scheduled-write",
                )
            }
            return
        yield "scheduled external write completed"

    return FunctionModel(
        stream_function=stream_external_write,
        model_name="scheduled-external-write-flow",
    )


async def test_worker_external_write_pauses_resumes_and_finalizes_schedule(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    scheduled_external_write_tool,
) -> None:
    schedule_id = await _create_due_schedule(
        committed_db_session_factory,
        tool_names=["scheduled_external_write"],
        execution_params={"envelope": {"side_effect_policy": "require_approval"}},
    )

    model = _scheduled_external_write_model()

    attempted = await run_once(
        owner_instance_id="test-worker",
        model=model,
    )

    assert attempted >= 1
    assert scheduled_external_write_tool["count"] == 0
    async with committed_db_session_factory() as db:
        await _set_schedule_tenant_context(db, schedule_id)
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_AWAITING_APPROVAL
        assert schedule_run.agent_run_id is not None
        assert schedule_run.conversation_id is not None

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.status == "awaiting_approval"
        suspended_state = load_suspended_run_state(agent_run)
        tool_call_id = suspended_state.pending_tool_call_ids[0]
        run_id = agent_run.id
        workspace_id = agent_run.workspace_id
        user_id = agent_run.user_id
        conversation_id = schedule_run.conversation_id

    await run_resume_worker(
        run_id=run_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        user_id=user_id,
        message_history=suspended_state.message_history,
        deferred_tool_results=DeferredToolResults(approvals={tool_call_id: ToolApproved()}),
        sink=NullSink(run_id=run_id, conversation_id=conversation_id),
        model=model,
    )

    assert scheduled_external_write_tool["count"] == 1

    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=workspace_id, user_id=user_id)
        schedule = await db.get(AgentSchedule, schedule_id)
        assert schedule is not None
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_COMPLETED
        assert schedule.is_active is False

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.status == "completed"
        assert agent_run.outcome == "success"
        assert agent_run.requests == 2


async def test_worker_request_budget_is_cumulative_across_approval_resume(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    scheduled_external_write_tool,
) -> None:
    schedule_id = await _create_due_schedule(
        committed_db_session_factory,
        tool_names=["scheduled_external_write"],
        execution_params={
            "envelope": {"side_effect_policy": "require_approval"},
            "completion_contract": {
                "required": False,
                "criteria": [],
                "max_requests": 1,
            },
        },
    )
    model = _scheduled_external_write_model()

    await run_once(owner_instance_id="test-worker", model=model)

    async with committed_db_session_factory() as db:
        await _set_schedule_tenant_context(db, schedule_id)
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_AWAITING_APPROVAL
        assert schedule_run.agent_run_id is not None
        assert schedule_run.conversation_id is not None

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.requests == 1
        assert agent_run.metadata_json["completion_contract"]["max_requests"] == 1
        assert agent_run.input_tokens is not None
        assert agent_run.output_tokens is not None
        observed_total_tokens = agent_run.input_tokens + agent_run.output_tokens
        assert observed_total_tokens > 0
        suspended_state = load_suspended_run_state(agent_run)
        tool_call_id = suspended_state.pending_tool_call_ids[0]
        run_id = agent_run.id
        workspace_id = agent_run.workspace_id
        user_id = agent_run.user_id
        conversation_id = schedule_run.conversation_id

    await run_resume_worker(
        run_id=run_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        user_id=user_id,
        message_history=suspended_state.message_history,
        deferred_tool_results=DeferredToolResults(approvals={tool_call_id: ToolApproved()}),
        sink=NullSink(run_id=run_id, conversation_id=conversation_id),
        model=model,
    )

    assert scheduled_external_write_tool["count"] == 1

    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=workspace_id, user_id=user_id)
        schedule = await db.get(AgentSchedule, schedule_id)
        assert schedule is not None
        assert schedule.is_active is False
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.status == "failed"
        assert agent_run.outcome == "budget_exhausted"
        assert agent_run.requests == 1
        assert agent_run.completion_json == {
            "error_code": "usage_limit_exceeded",
            "tripped_budget": {"kind": "requests", "limit": 1, "scope": "local"},
            "observed_total_tokens": observed_total_tokens,
            "requests": 1,
        }
        assert agent_run.metadata_json["effective_usage_limits"]["limits"]["request_limit"] == 1


async def test_run_once_provider_failure_disables_schedule_and_prunes_conversation(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_id = await _create_due_schedule(committed_db_session_factory)

    def broken_model(_resolved_model):
        raise ModelConfigurationError("Missing credential", details={"provider": "openai"})

    monkeypatch.setattr("services.agents.runtime.loop.build_model", broken_model)

    attempted = await run_once(owner_instance_id="test-worker")

    assert attempted >= 1
    async with committed_db_session_factory() as db:
        await _set_schedule_tenant_context(db, schedule_id)
        schedule = await db.get(AgentSchedule, schedule_id)
        assert schedule is not None
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
        assert schedule.is_active is False

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.status == "failed"
        assert agent_run.outcome == "error"

        conversation = await db.get(Conversation, schedule_run.conversation_id)
        assert conversation is not None
        assert conversation.deleted is True


async def test_run_once_shutdown_cancel_does_not_mark_schedule_cancelled(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_id = await _create_due_schedule(committed_db_session_factory)
    execution_started = asyncio.Event()

    async def fake_execute_prepared(prepared, *, owner_instance_id: str, model=None) -> None:
        assert owner_instance_id == prepared.owner_instance_id
        assert model is None
        execution_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(agent_runner, "_execute_prepared", fake_execute_prepared)

    run_task = asyncio.create_task(run_once(owner_instance_id="test-worker"))
    await asyncio.wait_for(execution_started.wait(), timeout=2)
    run_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run_task

    async with committed_db_session_factory() as db:
        await _set_schedule_tenant_context(db, schedule_id)
        schedule = await db.get(AgentSchedule, schedule_id)
        assert schedule is not None
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_RUNNING
        assert schedule.is_active is True
        assert schedule_run.last_error_code is None

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.status == "pending"


async def test_run_forever_cancels_in_flight_pass_after_shutdown_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_event = asyncio.Event()
    pass_started = asyncio.Event()
    pass_cancelled = asyncio.Event()

    async def fake_run_once(
        *,
        owner_instance_id: str,
        model=None,
        shutdown_event: asyncio.Event | None = None,
    ) -> int:
        assert owner_instance_id == "test-worker"
        assert model is None
        assert shutdown_event is not None
        pass_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass_cancelled.set()
            raise

    monkeypatch.setattr(agent_runner, "run_once", fake_run_once)
    monkeypatch.setattr(settings, "AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS", 0.01)

    worker_task = asyncio.create_task(
        agent_runner.run_forever(
            shutdown_event=shutdown_event,
            owner_instance_id="test-worker",
        )
    )
    await asyncio.wait_for(pass_started.wait(), timeout=1)
    shutdown_event.set()

    await asyncio.wait_for(worker_task, timeout=1)

    assert pass_cancelled.is_set()
