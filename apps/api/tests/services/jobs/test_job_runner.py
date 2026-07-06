# apps/api/tests/services/jobs/test_job_runner.py

"""Worker-level tests for the generic job runner."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import workers.job_runner as job_runner
from models.jobs import Job
from services.jobs.domain import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from services.jobs.enqueue_job import enqueue_job
from services.jobs.registry import JOB_HANDLERS, job_handler

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
