# apps/api/tests/services/agent_schedules/test_agent_runner.py

"""Worker-level tests for the scheduled agent runner."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import workers.agent_runner as agent_runner
from core.settings import settings
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import cancel_agent_run
from services.agent_runs.domain import RUN_STATUS_CANCELLED
from services.agent_schedules.runs import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_TERMINAL_FAILED,
)
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.heartbeat import cancel_target_if_run_cancelled
from services.agents.runtime.sinks import NullSink
from services.agents.runtime.tools.contract import TOOL_EFFECT_SCOPE_EXTERNAL, TOOL_EFFECT_WRITE
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from services.agents.runtime.worker import run_resume_worker
from tests.factories import build_user, build_workspace
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
        db.add_all([user, workspace])
        await db.flush()

        agent = Agent(
            name="Worker Agent",
            slug=f"worker-agent-{uuid4().hex[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider="openai",
            model="gpt-5.4-mini",
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
    )
    async def scheduled_external_write(value: str) -> dict[str, bool]:
        executions["count"] += 1
        return {"ok": bool(value)}

    yield executions
    RUNTIME_TOOL_CATALOG.pop(tool_name, None)


async def test_run_once_executes_due_once_schedule(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    schedule_id = await _create_due_schedule(committed_db_session_factory)

    attempted = await run_once(owner_instance_id="test-worker", model=TestModel(call_tools=[]))

    assert attempted >= 1
    async with committed_db_session_factory() as db:
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
        conversation = await db.get(Conversation, schedule_run.conversation_id)
        assert conversation is not None
        assert conversation.unread is True
        messages = (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == schedule_run.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        ).all()
        assert [message.role for message in messages] == ["user", "assistant"]


async def test_run_once_suspends_approval_required_schedule(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    schedule_id = await _create_due_schedule(
        committed_db_session_factory,
        tool_names=["test_add_numbers"],
        tool_policies={"test_add_numbers": "approval"},
    )

    attempted = await run_once(
        owner_instance_id="test-worker",
        model=TestModel(call_tools=["test_add_numbers"]),
    )

    assert attempted >= 1
    async with committed_db_session_factory() as db:
        schedule = await db.get(AgentSchedule, schedule_id)
        assert schedule is not None
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_AWAITING_APPROVAL
        assert schedule.is_active is True
        assert schedule.next_run_at is not None

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.status == "awaiting_approval"
        conversation = await db.get(Conversation, schedule_run.conversation_id)
        assert conversation is not None
        assert conversation.unread is True


async def test_worker_external_write_pauses_resumes_and_finalizes_schedule(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    scheduled_external_write_tool,
) -> None:
    schedule_id = await _create_due_schedule(
        committed_db_session_factory,
        tool_names=["scheduled_external_write"],
        execution_params={"envelope": {"side_effect_policy": "require_approval"}},
    )

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

    model = FunctionModel(
        stream_function=stream_external_write,
        model_name="scheduled-external-write-flow",
    )

    attempted = await run_once(
        owner_instance_id="test-worker",
        model=model,
    )

    assert attempted >= 1
    assert scheduled_external_write_tool["count"] == 0
    async with committed_db_session_factory() as db:
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
        conversation_id = schedule_run.conversation_id

    await run_resume_worker(
        run_id=run_id,
        conversation_id=conversation_id,
        message_history=suspended_state.message_history,
        deferred_tool_results=DeferredToolResults(approvals={tool_call_id: ToolApproved()}),
        sink=NullSink(run_id=run_id, conversation_id=conversation_id),
        model=model,
    )

    assert scheduled_external_write_tool["count"] == 1

    async with committed_db_session_factory() as db:
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

        conversation = await db.get(Conversation, schedule_run.conversation_id)
        assert conversation is not None
        assert conversation.deleted is True


async def test_run_once_finalizes_cooperatively_cancelled_schedule(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_id = await _create_due_schedule(committed_db_session_factory)

    async def fake_execute_prepared(prepared, *, owner_instance_id: str, model=None) -> None:
        assert owner_instance_id == "test-worker"
        assert model is None
        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, prepared.agent_run_id)
            assert run is not None
            await cancel_agent_run(db, run)
            await db.commit()
        raise asyncio.CancelledError

    monkeypatch.setattr(agent_runner, "_execute_prepared", fake_execute_prepared)

    attempted = await run_once(owner_instance_id="test-worker")

    assert attempted >= 1
    async with committed_db_session_factory() as db:
        schedule = await db.get(AgentSchedule, schedule_id)
        assert schedule is not None
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
        assert schedule.is_active is False
        assert schedule_run.last_error_code == "agent_run_cancelled"

        agent_run = await db.get(AgentRun, schedule_run.agent_run_id)
        assert agent_run is not None
        assert agent_run.status == "cancelled"


async def test_run_once_cancels_multiple_schedule_runs_in_one_batch(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_ids = [
        await _create_due_schedule(committed_db_session_factory),
        await _create_due_schedule(committed_db_session_factory),
    ]
    cancelled_run_ids: set[UUID] = set()
    cancelled_run_events: dict[UUID, asyncio.Event] = {}

    def event_for_run(run_id: UUID) -> asyncio.Event:
        event = cancelled_run_events.get(run_id)
        if event is None:
            event = asyncio.Event()
            cancelled_run_events[run_id] = event
        return event

    async def fake_status(*, run_id):
        return RUN_STATUS_CANCELLED if run_id in cancelled_run_ids else None

    async def fake_heartbeat(
        *,
        run_id,
        owner_instance_id: str,
        stop: asyncio.Event,
        cancel_target: asyncio.Task | None = None,
    ) -> None:
        cancelled_wait = asyncio.create_task(event_for_run(run_id).wait())
        stopped_wait = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait(
            {cancelled_wait, stopped_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with suppress(asyncio.CancelledError):
                await task
        if stopped_wait in done:
            return
        await cancel_target_if_run_cancelled(
            run_id=run_id,
            owner_instance_id=owner_instance_id,
            cancel_target=cancel_target,
        )

    async def fake_execute_prepared(prepared, *, owner_instance_id: str, model=None) -> None:
        assert owner_instance_id == "test-worker"
        assert model is None
        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, prepared.agent_run_id)
            assert run is not None
            await cancel_agent_run(db, run)
            await db.commit()
        cancelled_run_ids.add(prepared.agent_run_id)
        event_for_run(prepared.agent_run_id).set()
        await asyncio.Event().wait()

    monkeypatch.setattr(settings, "AGENT_SCHEDULE_WORKER_BATCH_SIZE", 2)
    monkeypatch.setattr(agent_runner, "_execute_prepared", fake_execute_prepared)
    monkeypatch.setattr(agent_runner, "heartbeat_agent_run_lease", fake_heartbeat)
    monkeypatch.setattr(
        "services.agents.runtime.heartbeat.read_agent_run_status_once",
        fake_status,
    )

    attempted = await asyncio.wait_for(
        run_once(owner_instance_id="test-worker"),
        timeout=2,
    )

    assert attempted >= 2
    async with committed_db_session_factory() as db:
        schedule_runs = (
            await db.scalars(
                select(AgentScheduleRun).where(AgentScheduleRun.schedule_id.in_(schedule_ids))
            )
        ).all()
        assert len(schedule_runs) == 2
        assert {schedule_run.status for schedule_run in schedule_runs} == {
            RUN_STATUS_TERMINAL_FAILED
        }
        agent_runs = (
            await db.scalars(
                select(AgentRun).where(
                    AgentRun.id.in_(
                        [
                            schedule_run.agent_run_id
                            for schedule_run in schedule_runs
                            if schedule_run.agent_run_id is not None
                        ]
                    )
                )
            )
        ).all()
        assert len(agent_runs) == 2
        assert {agent_run.status for agent_run in agent_runs} == {RUN_STATUS_CANCELLED}


async def test_run_once_shutdown_cancel_does_not_mark_schedule_cancelled(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_id = await _create_due_schedule(committed_db_session_factory)
    execution_started = asyncio.Event()

    async def fake_execute_prepared(prepared, *, owner_instance_id: str, model=None) -> None:
        assert owner_instance_id == "test-worker"
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


async def test_run_forever_waits_for_in_flight_pass_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_event = asyncio.Event()
    pass_started = asyncio.Event()
    release_pass = asyncio.Event()
    pass_completed = False

    async def fake_run_once(*, owner_instance_id: str, model=None) -> int:
        nonlocal pass_completed
        assert owner_instance_id == "test-worker"
        assert model is None
        pass_started.set()
        await release_pass.wait()
        pass_completed = True
        return 1

    monkeypatch.setattr(agent_runner, "run_once", fake_run_once)
    monkeypatch.setattr(settings, "AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS", 1)

    worker_task = asyncio.create_task(
        agent_runner.run_forever(
            shutdown_event=shutdown_event,
            owner_instance_id="test-worker",
        )
    )
    await asyncio.wait_for(pass_started.wait(), timeout=1)
    shutdown_event.set()
    release_pass.set()

    await asyncio.wait_for(worker_task, timeout=1)

    assert pass_completed is True


async def test_run_forever_cancels_in_flight_pass_after_shutdown_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_event = asyncio.Event()
    pass_started = asyncio.Event()
    pass_cancelled = asyncio.Event()

    async def fake_run_once(*, owner_instance_id: str, model=None) -> int:
        assert owner_instance_id == "test-worker"
        assert model is None
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
