# apps/api/tests/services/agent_schedules/test_agent_runner.py

"""Worker-level tests for the scheduled agent runner."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import workers.agent_runner as agent_runner
from core.settings import settings
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from services.agent_schedules.runs import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_TERMINAL_FAILED,
)
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.sinks import NullSink
from services.agents.runtime.worker import run_resume_worker
from tests.factories import build_user, build_workspace
from workers.agent_runner import run_once

pytestmark = pytest.mark.asyncio


async def _create_due_schedule(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tool_names: list[str] | None = None,
    tool_policies: dict[str, str] | None = None,
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
        )
        db.add(schedule)
        await db.flush()
        schedule_id = schedule.id
        await db.commit()
        return schedule_id


async def test_run_once_executes_due_once_schedule(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    schedule_id = await _create_due_schedule(committed_db_session_factory)

    attempted = await run_once(owner_instance_id="test-worker", model=TestModel())

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
        tool_names=["add_numbers"],
        tool_policies={"add_numbers": "approval"},
    )

    attempted = await run_once(owner_instance_id="test-worker", model=TestModel())

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


async def test_resume_worker_finalizes_scheduled_approval_resume(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    schedule_id = await _create_due_schedule(
        committed_db_session_factory,
        tool_names=["add_numbers"],
        tool_policies={"add_numbers": "approval"},
    )

    attempted = await run_once(owner_instance_id="test-worker", model=TestModel())

    assert attempted >= 1
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
        deferred_tool_results=DeferredToolResults(
            approvals={tool_call_id: ToolApproved(override_args={"a": 2, "b": 3})}
        ),
        sink=NullSink(run_id=run_id, conversation_id=conversation_id),
        model=TestModel(),
    )

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
