# apps/api/tests/services/jobs/test_job_runner.py

"""Worker-level tests for the generic job runner."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import workers.job_runner as job_runner
from core.database import (
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
)
from core.settings import settings
from models.agent import Agent
from models.jobs import Job
from models.user import User
from models.workspace import Workspace
from services.jobs.domain import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from services.jobs.enqueue_job import enqueue_job
from services.jobs.heartbeat_job_lease import heartbeat_job_lease
from services.jobs.reclaim_stale_jobs import reclaim_stale_jobs
from services.jobs.registry import JOB_HANDLERS, job_handler
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def registered_job_kind() -> AsyncIterator[str]:
    kind = f"tests.job_runner.{uuid4().hex}"

    async def handler(_db: AsyncSession, job: Job) -> None:
        job.payload = {**job.payload, "handled": True}

    job_handler(kind=kind, timeout=1.0)(handler)
    try:
        yield kind
    finally:
        JOB_HANDLERS.pop(kind, None)


async def _clear_jobs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as db:
        await db.execute(delete(Job))
        await db.commit()


async def test_run_once_executes_registered_kind(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    registered_job_kind: str,
) -> None:
    await _clear_jobs(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        job = await enqueue_job(db, kind=registered_job_kind)
        job_id = job.id
        await db.commit()

    attempted = await job_runner.run_once(owner_instance_id="test-worker")

    assert attempted >= 1
    async with committed_db_session_factory() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        assert job.status == JOB_STATUS_SUCCEEDED
        assert job.payload["handled"] is True
    await _clear_jobs(committed_db_session_factory)


async def test_run_once_executes_claimed_jobs_concurrently(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = f"tests.job_runner.parallel.{uuid4().hex}"
    both_started = asyncio.Event()
    active = 0
    peak_active = 0
    warning_passes = 0

    async def handler(_db: AsyncSession, _job: Job) -> None:
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        if active == 2:
            both_started.set()
        try:
            await asyncio.wait_for(both_started.wait(), timeout=1)
        finally:
            active -= 1

    async def record_warning_pass(_db: AsyncSession) -> None:
        nonlocal warning_passes
        warning_passes += 1

    job_handler(kind=kind, timeout=2.0)(handler)
    monkeypatch.setattr(settings, "WORKER_MAX_CONCURRENT_RUNS", 2)
    monkeypatch.setattr(job_runner, "log_job_concurrency_warnings", record_warning_pass)
    try:
        await _clear_jobs(committed_db_session_factory)
        async with committed_db_session_factory() as db:
            for index in range(3):
                await enqueue_job(db, kind=kind, payload={"index": index})
            await db.commit()

        attempted = await asyncio.wait_for(
            job_runner.run_once(owner_instance_id="parallel-worker", batch_size=3),
            timeout=2,
        )

        assert attempted == 3
        assert peak_active == 2
        assert warning_passes == 1
    finally:
        JOB_HANDLERS.pop(kind, None)
        await _clear_jobs(committed_db_session_factory)


async def test_heartbeat_prevents_reclaim_until_worker_stops(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _clear_jobs(committed_db_session_factory)
    owner_instance_id = "heartbeat-worker"
    async with committed_db_session_factory() as db:
        job = Job(
            kind="tests.job_runner.heartbeat",
            status=JOB_STATUS_RUNNING,
            attempts=1,
            locked_by=owner_instance_id,
            locked_at=datetime.now(UTC),
            lock_expires_at=datetime.now(UTC) + timedelta(seconds=0.04),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        heartbeat_job_lease(
            job_id=job_id,
            owner_instance_id=owner_instance_id,
            stop=stop,
            interval_seconds=0.01,
            lock_ttl_seconds=0.05,
        )
    )
    try:
        await asyncio.sleep(0.08)
        async with committed_db_session_factory() as db:
            assert await reclaim_stale_jobs(db) == 0
            await db.commit()
            persisted = await db.get(Job, job_id)
            assert persisted is not None
            assert persisted.status == JOB_STATUS_RUNNING
    finally:
        stop.set()
        await heartbeat_task

    await asyncio.sleep(0.06)
    async with committed_db_session_factory() as db:
        assert await reclaim_stale_jobs(db) == 1
        await db.commit()
        persisted = await db.get(Job, job_id)
        assert persisted is not None
        assert persisted.status == JOB_STATUS_PENDING
    await _clear_jobs(committed_db_session_factory)


async def test_runner_cancels_handler_after_lease_ownership_changes(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = f"tests.job_runner.lease_loss.{uuid4().hex}"
    owner_instance_id = "stale-worker"
    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()
    handler_completed = False

    async def handler(_db: AsyncSession, _job: Job) -> None:
        nonlocal handler_completed
        handler_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise
        handler_completed = True

    async def fast_heartbeat(**kwargs) -> None:
        await heartbeat_job_lease(
            **kwargs,
            interval_seconds=0.01,
            lock_ttl_seconds=0.1,
        )

    job_handler(kind=kind, timeout=2.0)(handler)
    monkeypatch.setattr(job_runner, "heartbeat_job_lease", fast_heartbeat)
    await _clear_jobs(committed_db_session_factory)
    try:
        async with committed_db_session_factory() as db:
            job = Job(
                kind=kind,
                status=JOB_STATUS_RUNNING,
                attempts=1,
                locked_by=owner_instance_id,
                locked_at=datetime.now(UTC),
                lock_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            db.add(job)
            await db.commit()
            job_id = job.id

        execution_task = asyncio.create_task(
            job_runner.execute_claimed_job(
                job_id,
                owner_instance_id=owner_instance_id,
            )
        )
        await asyncio.wait_for(handler_started.wait(), timeout=1)

        async with committed_db_session_factory() as db:
            persisted = await db.get(Job, job_id)
            assert persisted is not None
            persisted.locked_by = "replacement-worker"
            persisted.locked_at = datetime.now(UTC)
            persisted.lock_expires_at = datetime.now(UTC) + timedelta(minutes=1)
            await db.commit()

        await asyncio.wait_for(handler_cancelled.wait(), timeout=1)
        await asyncio.wait_for(execution_task, timeout=1)

        async with committed_db_session_factory() as db:
            persisted = await db.get(Job, job_id)
            assert persisted is not None
            assert persisted.status == JOB_STATUS_RUNNING
            assert persisted.locked_by == "replacement-worker"
        assert handler_completed is False
    finally:
        JOB_HANDLERS.pop(kind, None)
        await _clear_jobs(committed_db_session_factory)


async def test_workspace_handler_cannot_read_another_workspaces_rows(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    kind = f"tests.job_runner.rls.{uuid4().hex}"

    async def handler(db: AsyncSession, job: Job) -> None:
        job.payload = {
            **job.payload,
            "visible_agents": await db.scalar(select(func.count()).select_from(Agent)),
        }

    job_handler(kind=kind, timeout=1.0)(handler)
    user = build_user(email=f"job-rls-{uuid4().hex}@example.com")
    workspace_a = build_workspace(slug=f"job-rls-a-{uuid4().hex[:8]}")
    workspace_b = build_workspace(slug=f"job-rls-b-{uuid4().hex[:8]}")
    try:
        await _clear_jobs(committed_db_session_factory)
        async with committed_db_session_factory() as db:
            db.add_all([user, workspace_a, workspace_b])
            await db.commit()
            await set_session_tenant_context(
                db,
                workspace_id=workspace_a.id,
                user_id=user.id,
            )
            db.add(
                Agent(
                    name="Visible",
                    slug=f"visible-{uuid4().hex[:8]}",
                    instructions="Visible to workspace A.",
                    workspace_id=workspace_a.id,
                    created_by=user.id,
                )
            )
            await db.commit()
            await set_session_tenant_context(
                db,
                workspace_id=workspace_b.id,
                user_id=user.id,
            )
            db.add(
                Agent(
                    name="Hidden",
                    slug=f"hidden-{uuid4().hex[:8]}",
                    instructions="Hidden in workspace B.",
                    workspace_id=workspace_b.id,
                    created_by=user.id,
                )
            )
            await db.commit()
            job = await enqueue_job(db, kind=kind, workspace_id=workspace_a.id)
            job_id = job.id
            await db.commit()

        assert await job_runner.run_once(owner_instance_id="test-worker") >= 1

        async with get_maintenance_async_db_session_factory()() as maintenance_db:
            persisted = await maintenance_db.get(Job, job_id)
            assert persisted is not None
            assert persisted.payload["visible_agents"] == 1
    finally:
        JOB_HANDLERS.pop(kind, None)
        async with get_maintenance_async_db_session_factory()() as maintenance_db:
            await maintenance_db.execute(delete(Job).where(Job.kind == kind))
            await maintenance_db.execute(
                delete(Agent).where(Agent.workspace_id.in_([workspace_a.id, workspace_b.id]))
            )
            await maintenance_db.execute(
                delete(Workspace).where(Workspace.id.in_([workspace_a.id, workspace_b.id]))
            )
            await maintenance_db.execute(delete(User).where(User.id == user.id))
            await maintenance_db.commit()


async def test_handler_exception_retries(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    kind = f"tests.job_runner.error.{uuid4().hex}"

    async def handler(_db: AsyncSession, _job: Job) -> None:
        raise ValueError("bad handler")

    job_handler(kind=kind, timeout=1.0)(handler)
    try:
        await _clear_jobs(committed_db_session_factory)
        async with committed_db_session_factory() as db:
            job = await enqueue_job(db, kind=kind, max_attempts=2)
            job_id = job.id
            await db.commit()

        attempted = await job_runner.run_once(owner_instance_id="test-worker")

        assert attempted >= 1
        async with committed_db_session_factory() as db:
            job = await db.get(Job, job_id)
            assert job is not None
            assert job.status == JOB_STATUS_PENDING
            assert job.last_error_code == "ValueError"
    finally:
        JOB_HANDLERS.pop(kind, None)
        await _clear_jobs(committed_db_session_factory)


async def test_handler_timeout_records_retryable_failure(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    kind = f"tests.job_runner.timeout.{uuid4().hex}"

    async def handler(_db: AsyncSession, _job: Job) -> None:
        await asyncio.sleep(1)

    job_handler(kind=kind, timeout=0.01)(handler)
    try:
        await _clear_jobs(committed_db_session_factory)
        async with committed_db_session_factory() as db:
            job = await enqueue_job(db, kind=kind, max_attempts=2)
            job_id = job.id
            await db.commit()

        attempted = await job_runner.run_once(owner_instance_id="test-worker")

        assert attempted >= 1
        async with committed_db_session_factory() as db:
            job = await db.get(Job, job_id)
            assert job is not None
            assert job.status == JOB_STATUS_PENDING
            assert job.last_error_code == "handler_timeout"
    finally:
        JOB_HANDLERS.pop(kind, None)
        await _clear_jobs(committed_db_session_factory)


async def test_unknown_persisted_kind_fails_terminal(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _clear_jobs(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        job = Job(kind="tests.removed", max_attempts=5)
        db.add(job)
        await db.commit()
        job_id = job.id

    attempted = await job_runner.run_once(owner_instance_id="test-worker")

    assert attempted >= 1
    async with committed_db_session_factory() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JOB_STATUS_FAILED
        assert job.last_error_code == "unknown_kind"
        assert job.attempts == 1
    await _clear_jobs(committed_db_session_factory)


async def test_execute_claimed_job_skips_expired_lease(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    registered_job_kind: str,
) -> None:
    await _clear_jobs(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        job = Job(
            kind=registered_job_kind,
            status=JOB_STATUS_RUNNING,
            attempts=1,
            locked_by="test-worker",
            locked_at=datetime.now(UTC) - timedelta(minutes=10),
            lock_expires_at=datetime.now(UTC) - timedelta(minutes=5),
            payload={},
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    await job_runner.execute_claimed_job(job_id, owner_instance_id="test-worker")

    async with committed_db_session_factory() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        assert job is not None
        assert job.status == JOB_STATUS_RUNNING
        assert "handled" not in job.payload
    await _clear_jobs(committed_db_session_factory)
