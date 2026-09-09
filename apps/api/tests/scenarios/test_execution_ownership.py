"""Exercises bounded execution and family settlement through committed sessions."""

import asyncio
import importlib
from uuid import uuid4

import pytest
from pydantic_ai.models.function import FunctionModel

from core.settings import settings
from models.agent_run import AgentRun
from models.conversation import CONVERSATION_SOURCE_DELEGATED
from models.user import User
from models.workspace import Workspace
from services.agent_runs.claim_execution import claim_agent_run_execution
from services.agent_runs.create import create_agent_run
from services.agent_runs.settle_run_family import settle_run_family
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.execution_control import execution_control_for_run
from services.agents.runtime.run_manager import RunTaskRegistry
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.worker import run_turn_worker
from tests.factories import build_conversation
from tests.support.scenario import build_scenario_agent, run_scenario


async def test_admitted_deadline_bounds_worker_session_setup(
    committed_db_session_factory,
    monkeypatch,
):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, run, owner_instance_id=str(uuid4()))
        await db.commit()
        control = execution_control_for_run(run)
    control.deadline = asyncio.get_running_loop().time() + 0.05
    stopped = asyncio.Event()

    async def blocked_setup(_db):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr("services.agents.runtime.worker.configure_async_db_session", blocked_setup)
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    await asyncio.wait_for(
        run_turn_worker(
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            user_prompt="No provider request may start",
            sink=sink,
            owner_instance_id=control.owner_instance_id,
            execution_control=control,
        ),
        timeout=5,
    )
    assert stopped.is_set()
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run.status == "failed" and run.error_code == "run_duration_expired"
    assert [event.data["status"] for event in sink.events if event.event == "done"] == ["failed"]


async def test_admitted_deadline_bounds_context_loading(committed_db_session_factory, monkeypatch):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, run, owner_instance_id=str(uuid4()))
        await db.commit()
        control = execution_control_for_run(run)
    control.deadline = asyncio.get_running_loop().time() + 0.05
    entered, exited = asyncio.Event(), asyncio.Event()

    async def blocked_context(*_args, **_kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    implementation = importlib.import_module("services.agents.runtime.execute.execute_run")
    monkeypatch.setattr(implementation, "load_run_context", blocked_context)
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)

    async def worker():
        async with committed_db_session_factory() as db:
            return await execute_run(
                db,
                run_id=context.run_id,
                conversation_id=context.conversation_id,
                user_prompt="No provider request may start",
                sink=sink,
                owner_instance_id=control.owner_instance_id,
                execution_control=control,
            )

    registry = RunTaskRegistry(max_concurrent_turns=1)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            registry.spawn(context.run_id, worker(), sink=sink, execution_control=control),
            timeout=5,
        )
    assert entered.is_set() and exited.is_set()
    await registry.spawn(uuid4(), asyncio.sleep(0))
    assert [event.data["status"] for event in sink.events if event.event == "done"] == ["failed"]
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run.status == "failed" and run.error_code == "run_duration_expired"


async def test_provider_wait_expires_without_an_observer(committed_db_session_factory, monkeypatch):
    context = await build_scenario_agent(committed_db_session_factory)
    monkeypatch.setattr(settings, "AGENT_RUN_MAX_DURATION_SECONDS", 1)
    monkeypatch.setattr(settings, "AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def provider_wait(_messages, _info):
        entered.set()
        try:
            await asyncio.Event().wait()
            yield "Unreachable"
        finally:
            stopped.set()

    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            run_scenario(
                committed_db_session_factory,
                context,
                model=FunctionModel(stream_function=provider_wait),
                sink=sink,
            ),
            timeout=5,
        )
    assert entered.is_set()
    assert stopped.is_set()
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run.status == "failed"
        assert run.error_code == "run_duration_expired"
    assert sink.events[-1].data["status"] == "failed"


async def test_queued_deadline_prevents_worker_entry(committed_db_session_factory):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, run, owner_instance_id=str(uuid4()))
        await db.commit()
        control = execution_control_for_run(run)
    control.deadline = asyncio.get_running_loop().time() + 0.05
    registry = RunTaskRegistry(max_concurrent_turns=1)
    release = asyncio.Event()
    first = registry.spawn(uuid4(), release.wait())
    called = []

    async def worker():
        called.append(True)

    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    queued = registry.spawn(
        context.run_id,
        worker(),
        sink=sink,
        execution_control=control,
    )
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queued, timeout=5)
    finally:
        release.set()
        await first
    assert not called
    await registry.spawn(uuid4(), asyncio.sleep(0))
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run.status == "failed"
        assert run.error_code == "run_duration_expired"
    assert sink.events[-1].data["status"] == "failed"


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_stop_before_worker_entry_settles_claim(
    committed_db_session_factory,
    queued,
    shutdown,
):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, run, owner_instance_id=str(uuid4()))
        await db.commit()
        control = execution_control_for_run(run)
    registry = RunTaskRegistry(max_concurrent_turns=1)
    called = []

    async def worker():
        called.append(True)

    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    release = asyncio.Event()
    queue_entered = asyncio.Event()
    first = None
    if queued:
        first = registry.spawn(uuid4(), release.wait())
        emit = sink.emit

        async def observe_queue(event):
            await emit(event)
            if getattr(event, "status", None) == "queued":
                queue_entered.set()

        sink.emit = observe_queue
    task = registry.spawn(context.run_id, worker(), sink=sink, execution_control=control)
    try:
        if queued:
            await asyncio.wait_for(queue_entered.wait(), timeout=2)
        if shutdown:
            if queued:
                await registry.drain(max_wait_seconds=0)
            else:
                task.cancel("run_process_shutdown")
        else:
            assert registry.cancel(context.run_id)
        await asyncio.gather(task, return_exceptions=True)
    finally:
        release.set()
        if first is not None:
            await asyncio.gather(first, return_exceptions=True)
    await registry.drain(max_wait_seconds=5)
    assert not called
    await registry.spawn(uuid4(), asyncio.sleep(0))
    expected = "failed" if shutdown else "cancelled"
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run.status == expected
        if shutdown:
            assert run.error_code == "run_process_shutdown"
    assert [event.data["status"] for event in sink.events if event.event == "done"] == [expected]


async def test_family_cancellation_finds_children_without_approval_metadata(
    committed_db_session_factory,
):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        conversation = build_conversation(
            user=await db.get(User, root.user_id),
            workspace=await db.get(Workspace, root.workspace_id),
            active_agent_id=root.agent_id,
            source=CONVERSATION_SOURCE_DELEGATED,
        )
        db.add(conversation)
        await db.flush()
        child = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=root.agent_id,
            workspace_id=root.workspace_id,
            user_id=root.user_id,
            trigger="delegated",
            parent_run_id=root.id,
            delegation_depth=1,
        )
        child_id = child.id
        await db.commit()
    async with committed_db_session_factory() as db:
        changed = await settle_run_family(db, run_id=context.run_id, status="cancelled")
        assert {item.id for item in changed} == {context.run_id, child_id}
        await db.commit()
    async with committed_db_session_factory() as db:
        assert (await db.get(AgentRun, child_id)).status == "cancelled"
        assert await settle_run_family(db, run_id=context.run_id, status="cancelled") == []
