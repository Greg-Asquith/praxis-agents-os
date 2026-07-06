# apps/api/tests/services/jobs/test_claim_jobs.py

"""Tests for generic job claiming."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.jobs import Job
from services.jobs.claim_jobs import claim_jobs
from services.jobs.domain import JOB_STATUS_PENDING, JOB_STATUS_RUNNING
from tests.factories import build_job, build_workspace

pytestmark = pytest.mark.asyncio


async def test_claim_jobs_orders_by_priority_then_run_after(db_session: AsyncSession) -> None:
    await db_session.execute(delete(Job))
    await db_session.flush()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    first = build_job(priority=1, run_after=now - timedelta(seconds=5), payload={"job": 1})
    second = build_job(priority=10, run_after=now - timedelta(seconds=10), payload={"job": 2})
    future = build_job(priority=0, run_after=now + timedelta(minutes=1), payload={"job": 3})
    db_session.add_all([second, first, future])
    await db_session.flush()

    claimed = await claim_jobs(db_session, owner_instance_id="worker", now=now, batch_size=10)

    assert [job.id for job in claimed] == [first.id, second.id]
    assert future.status == JOB_STATUS_PENDING
    assert first.status == JOB_STATUS_RUNNING
    assert first.attempts == 1
    assert first.locked_by == "worker"


async def test_concurrent_claims_split_without_overlap(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with committed_db_session_factory() as db:
        await db.execute(delete(Job))
        jobs = [build_job(kind="jobs.sweep_terminal", payload={"n": index}) for index in range(4)]
        db.add_all(jobs)
        await db.commit()

    async with committed_db_session_factory() as first_db:
        first_claim = await claim_jobs(
            first_db,
            owner_instance_id="worker-1",
            batch_size=2,
        )
        async with committed_db_session_factory() as second_db:
            second_claim = await claim_jobs(
                second_db,
                owner_instance_id="worker-2",
                batch_size=2,
            )
            await second_db.commit()
        await first_db.commit()

    assert {job.id for job in first_claim}.isdisjoint({job.id for job in second_claim})
    assert len(first_claim) == 2
    assert len(second_claim) == 2


async def test_claim_logs_workspace_concurrency_warning(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    claim_jobs_module = importlib.import_module("services.jobs.claim_jobs")

    await db_session.execute(delete(Job))
    await db_session.flush()
    monkeypatch.setattr(claim_jobs_module.settings, "JOBS_WORKSPACE_CONCURRENCY_LIMIT", 1)
    warnings: list[str] = []

    def record_warning(message: str, *args: object, **kwargs: object) -> None:
        warnings.append(message)

    monkeypatch.setattr(claim_jobs_module.logger, "warning", record_warning)
    workspace = build_workspace(slug=f"job-limit-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add_all(
        [
            build_job(workspace_id=workspace.id, payload={"n": 1}),
            build_job(workspace_id=workspace.id, payload={"n": 2}),
        ]
    )
    await db_session.flush()

    await claim_jobs(db_session, owner_instance_id="worker", batch_size=2)

    assert any("exceeds configured warning threshold" in message for message in warnings)
