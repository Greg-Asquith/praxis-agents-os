"""Run-to-completion worker lifecycle tests."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import workers.agent_runner as agent_runner
import workers.job_runner as job_runner
import workers.main as worker_main
from core.database import get_maintenance_async_db_session_factory
from core.settings import Settings, settings
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.jobs import Job
from services.agent_schedules.runs import RUN_STATUS_COMPLETED
from services.jobs.domain import JOB_STATUS_PENDING, JOB_STATUS_SUCCEEDED
from services.jobs.enqueue_job import enqueue_job
from services.jobs.registry import JOB_HANDLERS, job_handler
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def drain_job_kind() -> AsyncIterator[tuple[str, dict[str, int]]]:
    kind = f"tests.worker_drain.{uuid4().hex}"
    executions: dict[str, int] = {}

    async def handler(_db: AsyncSession, job: Job) -> None:
        job_id = str(job.id)
        executions[job_id] = executions.get(job_id, 0) + 1

    job_handler(kind=kind, timeout=1.0)(handler)
    try:
        yield kind, executions
    finally:
        JOB_HANDLERS.pop(kind, None)


def _disable_periodic_enqueuers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(_db: AsyncSession) -> None:
        return None

    for target in (
        "services.jobs.handlers.sweep_terminal_jobs.ensure_sweep_job",
        "services.jobs.handlers.sweep_deleted_files.ensure_files_sweep_job",
        "services.jobs.handlers.sweep_expired_artifact_shares.ensure_artifact_shares_sweep_job",
        "services.jobs.handlers.sweep_expired_audit_events.ensure_audit_event_sweep_job",
        "services.jobs.handlers.sweep_expired_security_events.ensure_security_event_sweep_job",
        "services.jobs.handlers.sweep_expired_scratch.ensure_scratch_sweep_job",
        "services.jobs.handlers.sweep_rate_limit_attempts.ensure_rate_limit_sweep_job",
        "workers.job_runner.ensure_integrations_sweep_job",
        "workers.job_runner.ensure_memory_sweep_job",
        "workers.job_runner.ensure_integrations_rediscover_job",
        "workers.job_runner.ensure_refresh_webhooks_job",
    ):
        monkeypatch.setattr(target, noop)


async def _clear_jobs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as db:
        await db.execute(delete(Job))
        await db.commit()


async def _create_due_schedule(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    async with session_factory() as db:
        user = build_user(email=f"drain-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"drain-{uuid4().hex[:8]}")
        membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
        db.add_all([user, workspace, membership])
        await db.flush()
        agent = Agent(
            name="Drain Agent",
            slug=f"drain-agent-{uuid4().hex[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider="openai",
            model="gpt-5.4-mini",
            tool_names=[],
        )
        db.add(agent)
        await db.flush()
        due_at = datetime.now(UTC) - timedelta(minutes=1)
        schedule = AgentSchedule(
            agent_id=agent.id,
            user_id=user.id,
            workspace_id=workspace.id,
            schedule_type="once",
            run_once_at=due_at,
            next_run_at=due_at,
            default_prompt="Run during the drain test",
        )
        db.add(schedule)
        await db.commit()
        return schedule.id


async def test_drain_mode_with_empty_queues_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"agent": 0, "job": 0}

    async def drain_agent(*, shutdown_event: asyncio.Event) -> int:
        assert not shutdown_event.is_set()
        calls["agent"] += 1
        return 0

    async def drain_jobs(*, shutdown_event: asyncio.Event) -> int:
        assert not shutdown_event.is_set()
        calls["job"] += 1
        return 0

    async def close_connections() -> None:
        return None

    monkeypatch.setattr(settings, "WORKER_MODE", "drain")
    monkeypatch.setattr(worker_main.agent_runner, "run_drain", drain_agent)
    monkeypatch.setattr(worker_main.job_runner, "run_drain", drain_jobs)
    monkeypatch.setattr(worker_main, "close_db_connections", close_connections)

    assert await asyncio.wait_for(worker_main.main(), timeout=1) == 0
    assert calls == {"agent": 1, "job": 1}


async def test_drain_mode_rechecks_both_queues_after_either_does_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs_first_idle = asyncio.Event()
    follow_on_job_ready = False
    follow_on_job_processed = False
    calls = {"agent": 0, "job": 0}

    async def drain_agent(*, shutdown_event: asyncio.Event) -> int:
        nonlocal follow_on_job_ready
        assert not shutdown_event.is_set()
        calls["agent"] += 1
        if calls["agent"] == 1:
            await jobs_first_idle.wait()
            follow_on_job_ready = True
            return 1
        return 0

    async def drain_jobs(*, shutdown_event: asyncio.Event) -> int:
        nonlocal follow_on_job_processed
        assert not shutdown_event.is_set()
        calls["job"] += 1
        if calls["job"] == 1:
            jobs_first_idle.set()
            return 0
        if calls["job"] == 2:
            assert follow_on_job_ready is True
            follow_on_job_processed = True
            return 1
        return 0

    monkeypatch.setattr(worker_main.agent_runner, "run_drain", drain_agent)
    monkeypatch.setattr(worker_main.job_runner, "run_drain", drain_jobs)

    assert await asyncio.wait_for(worker_main._run_drain_mode(asyncio.Event()), timeout=1) == 0
    assert follow_on_job_processed is True
    assert calls == {"agent": 3, "job": 3}


async def test_drain_budget_finishes_in_flight_pass_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_flight_started = asyncio.Event()
    in_flight_finished = asyncio.Event()

    async def drain_agent(*, shutdown_event: asyncio.Event) -> int:
        await shutdown_event.wait()
        return 0

    async def drain_jobs(*, shutdown_event: asyncio.Event) -> int:
        in_flight_started.set()
        await shutdown_event.wait()
        in_flight_finished.set()
        return 0

    monkeypatch.setattr(settings, "WORKER_DRAIN_MAX_SECONDS", 0.01)
    monkeypatch.setattr(worker_main.agent_runner, "run_drain", drain_agent)
    monkeypatch.setattr(worker_main.job_runner, "run_drain", drain_jobs)

    result = await asyncio.wait_for(worker_main._run_drain_mode(asyncio.Event()), timeout=1)

    assert result == 0
    assert in_flight_started.is_set()
    assert in_flight_finished.is_set()


async def test_drain_runner_exception_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def drain_agent(*, shutdown_event: asyncio.Event) -> None:
        raise RuntimeError("runner failed")

    async def drain_jobs(*, shutdown_event: asyncio.Event) -> int:
        await shutdown_event.wait()
        return 0

    monkeypatch.setattr(worker_main.agent_runner, "run_drain", drain_agent)
    monkeypatch.setattr(worker_main.job_runner, "run_drain", drain_jobs)

    assert await asyncio.wait_for(worker_main._run_drain_mode(asyncio.Event()), timeout=1) == 1


async def test_queued_job_and_due_schedule_are_processed_before_drain_exits(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    drain_job_kind: tuple[str, dict[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind, executions = drain_job_kind
    _disable_periodic_enqueuers(monkeypatch)
    await _clear_jobs(committed_db_session_factory)
    schedule_id = await _create_due_schedule(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        job = await enqueue_job(db, kind=kind)
        job_id = job.id
        await db.commit()

    shutdown_event = asyncio.Event()
    await asyncio.gather(
        agent_runner.run_drain(
            shutdown_event=shutdown_event,
            owner_instance_id="drain-agent-worker",
            model=TestModel(call_tools=[]),
        ),
        job_runner.run_drain(
            shutdown_event=shutdown_event,
            owner_instance_id="drain-job-worker",
        ),
    )

    async with get_maintenance_async_db_session_factory()() as db:
        persisted_job = await db.get(Job, job_id)
        schedule_run = await db.scalar(
            select(AgentScheduleRun).where(AgentScheduleRun.schedule_id == schedule_id)
        )
        assert persisted_job is not None
        assert persisted_job.status == JOB_STATUS_SUCCEEDED
        assert executions == {str(job_id): 1}
        assert schedule_run is not None
        assert schedule_run.status == RUN_STATUS_COMPLETED
    await _clear_jobs(committed_db_session_factory)


async def test_job_enqueued_by_periodic_enqueuer_is_processed(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    drain_job_kind: tuple[str, dict[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind, executions = drain_job_kind
    _disable_periodic_enqueuers(monkeypatch)
    await _clear_jobs(committed_db_session_factory)
    enqueued = False

    async def enqueue_once(db: AsyncSession) -> None:
        nonlocal enqueued
        if enqueued:
            return
        enqueued = True
        await enqueue_job(db, kind=kind)

    monkeypatch.setattr(
        "services.jobs.handlers.sweep_terminal_jobs.ensure_sweep_job",
        enqueue_once,
    )

    await job_runner.run_drain(
        shutdown_event=asyncio.Event(),
        owner_instance_id="enqueuer-drain-worker",
    )

    assert enqueued is True
    assert len(executions) == 1
    assert set(executions.values()) == {1}
    await _clear_jobs(committed_db_session_factory)


async def test_schedule_drain_admits_up_to_shared_capacity_per_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_sizes: list[int | None] = []
    expected_shutdown_event = asyncio.Event()

    async def run_once(
        *,
        owner_instance_id: str,
        model=None,
        batch_size: int | None = None,
        shutdown_event: asyncio.Event | None = None,
    ) -> int:
        assert owner_instance_id == "single-claim-agent-worker"
        assert model is None
        assert shutdown_event is expected_shutdown_event
        batch_sizes.append(batch_size)
        return 0

    monkeypatch.setattr(settings, "WORKER_MAX_CONCURRENT_RUNS", 3)
    monkeypatch.setattr(agent_runner, "run_once", run_once)

    claimed_count = await agent_runner.run_drain(
        shutdown_event=expected_shutdown_event,
        owner_instance_id="single-claim-agent-worker",
    )

    assert claimed_count == 0
    assert batch_sizes == [3]


async def test_schedule_drain_allows_admitted_run_to_finish_after_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def run_once(
        *,
        owner_instance_id: str,
        model=None,
        batch_size: int | None = None,
        shutdown_event: asyncio.Event | None = None,
    ) -> int:
        assert owner_instance_id == "finish-agent-worker"
        assert model is None
        assert batch_size == settings.WORKER_MAX_CONCURRENT_RUNS
        assert shutdown_event is not None
        started.set()
        await release.wait()
        return 1

    monkeypatch.setattr(agent_runner, "run_once", run_once)
    shutdown_event = asyncio.Event()
    drain_task = asyncio.create_task(
        agent_runner.run_drain(
            shutdown_event=shutdown_event,
            owner_instance_id="finish-agent-worker",
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    shutdown_event.set()
    await asyncio.sleep(0.05)

    assert drain_task.done() is False

    release.set()
    assert await asyncio.wait_for(drain_task, timeout=1) == 1


async def test_shutdown_mid_queue_leaves_unclaimed_jobs_pending(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = f"tests.worker_drain.blocking.{uuid4().hex}"
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_db: AsyncSession, _job: Job) -> None:
        started.set()
        await release.wait()

    job_handler(kind=kind, timeout=1.0)(handler)
    _disable_periodic_enqueuers(monkeypatch)
    monkeypatch.setattr(settings, "JOBS_WORKER_BATCH_SIZE", 3)
    monkeypatch.setattr(settings, "WORKER_MAX_CONCURRENT_RUNS", 1)
    await _clear_jobs(committed_db_session_factory)
    try:
        async with committed_db_session_factory() as db:
            jobs = [
                await enqueue_job(db, kind=kind, payload={"index": index}) for index in range(2)
            ]
            job_ids = [job.id for job in jobs]
            await db.commit()

        shutdown_event = asyncio.Event()
        drain_task = asyncio.create_task(
            job_runner.run_drain(
                shutdown_event=shutdown_event,
                owner_instance_id="budget-drain-worker",
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        shutdown_event.set()
        release.set()
        await asyncio.wait_for(drain_task, timeout=1)

        async with committed_db_session_factory() as db:
            persisted = (await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
            assert sum(job.status == JOB_STATUS_SUCCEEDED for job in persisted) == 1
            pending = [job for job in persisted if job.status == JOB_STATUS_PENDING]
            assert len(pending) == 1
            assert pending[0].locked_by is None
    finally:
        JOB_HANDLERS.pop(kind, None)
        await _clear_jobs(committed_db_session_factory)


async def test_overlapping_drains_execute_each_job_once(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    drain_job_kind: tuple[str, dict[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind, executions = drain_job_kind
    _disable_periodic_enqueuers(monkeypatch)
    monkeypatch.setattr(settings, "JOBS_WORKER_BATCH_SIZE", 2)
    await _clear_jobs(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        jobs = [await enqueue_job(db, kind=kind, payload={"index": index}) for index in range(8)]
        job_ids = [job.id for job in jobs]
        await db.commit()

    await asyncio.gather(
        job_runner.run_drain(
            shutdown_event=asyncio.Event(),
            owner_instance_id="overlap-worker-a",
        ),
        job_runner.run_drain(
            shutdown_event=asyncio.Event(),
            owner_instance_id="overlap-worker-b",
        ),
    )

    async with committed_db_session_factory() as db:
        persisted = (await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
        assert len(persisted) == len(job_ids)
        assert all(job.status == JOB_STATUS_SUCCEEDED for job in persisted)
        assert all(job.attempts == 1 for job in persisted)
        assert executions == {str(job_id): 1 for job_id in job_ids}
    await _clear_jobs(committed_db_session_factory)


async def test_worker_settings_validate_mode_and_positive_budget() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.WORKER_MODE == "forever"
    assert defaults.WORKER_MAX_CONCURRENT_RUNS == 4
    with pytest.raises(ValidationError):
        Settings(_env_file=None, WORKER_MODE="once")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, WORKER_DRAIN_MAX_SECONDS=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, WORKER_MAX_CONCURRENT_RUNS=0)
