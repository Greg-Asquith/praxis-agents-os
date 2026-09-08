"""Exercises competing invocation and family mutations in committed sessions."""

import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai.usage import RunUsage
from sqlalchemy import select

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.jobs import Job
from models.user import User
from models.workspace import Workspace
from services.agent_runs.claim_execution import claim_agent_run_execution
from services.agent_runs.create import create_agent_run
from services.agent_runs.reap_abandoned import reap_abandoned_runs
from services.agent_runs.settle_run_family import settle_run_family
from services.agents.runtime.execution_control import ExecutionPhase, execution_control_for_run
from services.agents.runtime.heartbeat import renew_agent_run_lease_once
from services.agents.runtime.run_persistence import persist_successful_run
from services.jobs.handlers.sweep_abandoned_agent_runs import (
    SWEEP_ABANDONED_AGENT_RUNS_KIND,
    ensure_abandoned_agent_run_sweep_job,
    sweep_abandoned_agent_runs,
)
from tests.factories import build_conversation
from tests.support.scenario import build_scenario_agent


@pytest.mark.parametrize("status", ["completed", "awaiting_approval"])
async def test_committed_own_finalisation_survives_delayed_heartbeat(
    committed_db_session_factory,
    monkeypatch,
    status,
):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, run, owner_instance_id=str(uuid4()))
        await db.commit()
        control = execution_control_for_run(run)
    heartbeat = importlib.import_module("services.agents.runtime.heartbeat")
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_renewal(**kwargs):
        entered.set()
        await release.wait()
        return await renew_agent_run_lease_once(**kwargs)

    monkeypatch.setattr(heartbeat, "renew_agent_run_lease_once", delayed_renewal)
    target = asyncio.create_task(asyncio.Event().wait())
    ticker = asyncio.create_task(
        heartbeat.heartbeat_agent_run_lease(
            execution_control=control,
            stop=asyncio.Event(),
            cancel_target=target,
            renew_immediately=True,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        control.phase = ExecutionPhase.FINALISING
        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, context.run_id)
            run.status = status
            run.lease_expires_at = None
            await db.commit()
        release.set()
        await asyncio.wait_for(ticker, timeout=3)
        assert control.reason is None
        assert not target.done()
    finally:
        target.cancel()
        ticker.cancel()
        await asyncio.gather(target, ticker, return_exceptions=True)


async def test_competing_claims_and_delayed_old_heartbeat(committed_db_session_factory):
    context = await build_scenario_agent(committed_db_session_factory)
    ready = asyncio.Barrier(2)

    async def claim(owner):
        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, context.run_id)
            await ready.wait()
            try:
                await claim_agent_run_execution(db, run, owner_instance_id=owner)
                await db.commit()
                return True
            except ConflictError:
                await db.rollback()
                return False

    owners = [str(uuid4()), str(uuid4())]
    results = await asyncio.wait_for(asyncio.gather(*(claim(owner) for owner in owners)), timeout=5)
    assert sorted(results) == [False, True]
    winner, loser = owners[results.index(True)], owners[results.index(False)]
    assert not await renew_agent_run_lease_once(
        run_id=context.run_id,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        owner_instance_id=loser,
    )
    assert await renew_agent_run_lease_once(
        run_id=context.run_id,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        owner_instance_id=winner,
    )
    async with committed_db_session_factory() as db:
        assert (await db.get(AgentRun, context.run_id)).owner_instance_id == winner


async def test_periodic_recovery_without_reads_deduplicates_concurrent_startup(
    committed_db_session_factory,
):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, root, owner_instance_id=str(uuid4()))
        root.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    ready = asyncio.Barrier(2)

    async def ensure():
        async with committed_db_session_factory() as db:
            await ready.wait()
            job = await ensure_abandoned_agent_run_sweep_job(db)
            await db.commit()
            return job.id

    first, second = await asyncio.wait_for(asyncio.gather(ensure(), ensure()), timeout=5)
    assert first == second
    async with committed_db_session_factory() as db:
        job = await db.get(Job, first)
        job.status = "running"
        await sweep_abandoned_agent_runs(db, job)
        await sweep_abandoned_agent_runs(db, job)
        job.status = "succeeded"
        await db.commit()
    async with committed_db_session_factory() as db:
        assert (await db.get(AgentRun, context.run_id)).status == "failed"
        pending = list(
            await db.scalars(
                select(Job).where(
                    Job.kind == SWEEP_ABANDONED_AGENT_RUNS_KIND, Job.status == "pending"
                )
            )
        )
        assert len(pending) == 1
        assert pending[0].run_after > datetime.now(UTC)


@pytest.mark.parametrize("parent_first", [False, True])
async def test_parent_failure_races_child_creation(committed_db_session_factory, parent_first):
    context = await build_scenario_agent(committed_db_session_factory)
    child_ready, release_child = asyncio.Event(), asyncio.Event()
    if parent_first:
        async with committed_db_session_factory() as db:
            await settle_run_family(db, run_id=context.run_id, error_code="parent_failed")
            await db.commit()

    async def create_child():
        async with committed_db_session_factory() as db:
            conversation = build_conversation(
                user=await db.get(User, context.user_id),
                workspace=await db.get(Workspace, context.workspace_id),
                active_agent_id=context.agent_id,
            )
            db.add(conversation)
            await db.flush()
            child = await create_agent_run(
                db,
                conversation_id=conversation.id,
                agent_id=context.agent_id,
                workspace_id=context.workspace_id,
                user_id=context.user_id,
                trigger="delegated",
                parent_run_id=context.run_id,
                delegation_depth=1,
            )
            child_ready.set()
            await release_child.wait()
            await db.commit()
            return child.id

    if parent_first:
        with pytest.raises(ConflictError, match="Parent run"):
            await create_child()
        return

    async def fail_parent():
        async with committed_db_session_factory() as db:
            await settle_run_family(db, run_id=context.run_id, error_code="parent_failed")
            await db.commit()

    child_task = asyncio.create_task(create_child())
    failure_task = None
    try:
        await asyncio.wait_for(child_ready.wait(), timeout=3)
        failure_task = asyncio.create_task(fail_parent())
        release_child.set()
        child_id, _ = await asyncio.wait_for(asyncio.gather(child_task, failure_task), timeout=5)
    finally:
        release_child.set()
        tasks = [task for task in (child_task, failure_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    async with committed_db_session_factory() as db:
        assert (await db.get(AgentRun, context.run_id)).status == "failed"
        assert (await db.get(AgentRun, child_id)).status == "failed"


async def test_reaper_cancel_and_finalise_preserve_one_family_verdict(committed_db_session_factory):
    context = await build_scenario_agent(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        await claim_agent_run_execution(db, root, owner_instance_id=str(uuid4()))
        root.status = "running"
        conversation = build_conversation(
            user=await db.get(User, context.user_id),
            workspace=await db.get(Workspace, context.workspace_id),
            active_agent_id=context.agent_id,
        )
        db.add(conversation)
        await db.flush()
        child = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=context.agent_id,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            trigger="delegated",
            parent_run_id=root.id,
            delegation_depth=1,
        )
        child_id = child.id
        root.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    ready = asyncio.Barrier(3)

    async def settle(operation):
        async with committed_db_session_factory() as db:
            await ready.wait()
            if operation == "reap":
                await reap_abandoned_runs(db, run_id=context.run_id)
            elif operation == "cancel":
                await settle_run_family(db, run_id=context.run_id, status="cancelled")
            else:
                await persist_successful_run(
                    db,
                    run_id=context.run_id,
                    conversation_id=context.conversation_id,
                    terminal_result=SimpleNamespace(new_messages=list, usage=RunUsage()),
                    client_message_id=None,
                )
            await db.commit()

    await asyncio.wait_for(
        asyncio.gather(*(settle(op) for op in ("reap", "cancel", "finalise"))), timeout=5
    )
    async with committed_db_session_factory() as db:
        root = await db.get(AgentRun, context.run_id)
        child = await db.get(AgentRun, child_id)
        assert root.status in {"failed", "cancelled"}
        assert child.status == root.status
        assert root.lease_expires_at is None and child.lease_expires_at is None
