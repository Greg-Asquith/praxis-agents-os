# apps/api/tests/services/jobs/test_claim_jobs.py

"""Tests for generic job claiming."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.jobs import Job
from services.jobs.claim_jobs import claim_jobs
from services.jobs.domain import JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_SUCCEEDED
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


async def test_claim_jobs_skips_workspaces_at_running_cap(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    claim_jobs_module = importlib.import_module("services.jobs.claim_jobs")

    await db_session.execute(delete(Job))
    await db_session.flush()
    monkeypatch.setattr(claim_jobs_module.settings, "JOBS_WORKSPACE_CONCURRENCY_LIMIT", 2)
    capped_workspace = build_workspace(slug=f"job-capped-{uuid4().hex[:8]}")
    open_workspace = build_workspace(slug=f"job-open-{uuid4().hex[:8]}")
    db_session.add_all([capped_workspace, open_workspace])
    await db_session.flush()
    running_jobs = [
        build_job(
            workspace_id=capped_workspace.id,
            status=JOB_STATUS_RUNNING,
            payload={"running": index},
        )
        for index in range(2)
    ]
    capped_pending = build_job(workspace_id=capped_workspace.id, payload={"pending": "capped"})
    open_pending = build_job(workspace_id=open_workspace.id, payload={"pending": "open"})
    system_pending = build_job(payload={"pending": "system"})
    db_session.add_all([*running_jobs, capped_pending, open_pending, system_pending])
    await db_session.flush()

    claimed = await claim_jobs(db_session, owner_instance_id="worker", batch_size=10)

    claimed_ids = {job.id for job in claimed}
    assert capped_pending.id not in claimed_ids
    assert open_pending.id in claimed_ids
    assert system_pending.id in claimed_ids
    assert capped_pending.status == JOB_STATUS_PENDING

    for job in running_jobs:
        job.status = JOB_STATUS_SUCCEEDED
    await db_session.flush()

    second_claim = await claim_jobs(db_session, owner_instance_id="worker-2", batch_size=10)

    assert capped_pending.id in {job.id for job in second_claim}


async def test_claim_jobs_limits_pending_claims_per_workspace(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    claim_jobs_module = importlib.import_module("services.jobs.claim_jobs")

    await db_session.execute(delete(Job))
    await db_session.flush()
    monkeypatch.setattr(claim_jobs_module.settings, "JOBS_WORKSPACE_CONCURRENCY_LIMIT", 2)
    busy_workspace = build_workspace(slug=f"job-busy-{uuid4().hex[:8]}")
    other_workspace = build_workspace(slug=f"job-other-{uuid4().hex[:8]}")
    db_session.add_all([busy_workspace, other_workspace])
    await db_session.flush()
    busy_pending = [
        build_job(workspace_id=busy_workspace.id, payload={"busy": index}) for index in range(5)
    ]
    other_pending = build_job(workspace_id=other_workspace.id, payload={"other": True})
    db_session.add_all([*busy_pending, other_pending])
    await db_session.flush()

    claimed = await claim_jobs(db_session, owner_instance_id="worker", batch_size=10)

    claimed_ids = {job.id for job in claimed}
    assert sum(job.id in claimed_ids for job in busy_pending) == 2
    assert other_pending.id in claimed_ids
    assert sum(job.status == JOB_STATUS_PENDING for job in busy_pending) == 3


async def test_claim_jobs_only_uses_remaining_workspace_slots(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    claim_jobs_module = importlib.import_module("services.jobs.claim_jobs")

    await db_session.execute(delete(Job))
    await db_session.flush()
    monkeypatch.setattr(claim_jobs_module.settings, "JOBS_WORKSPACE_CONCURRENCY_LIMIT", 3)
    workspace = build_workspace(slug=f"job-slots-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    running_jobs = [
        build_job(workspace_id=workspace.id, status=JOB_STATUS_RUNNING, payload={"running": index})
        for index in range(2)
    ]
    pending_jobs = [
        build_job(workspace_id=workspace.id, payload={"pending": index}) for index in range(4)
    ]
    db_session.add_all([*running_jobs, *pending_jobs])
    await db_session.flush()

    claimed = await claim_jobs(db_session, owner_instance_id="worker", batch_size=10)

    claimed_ids = {job.id for job in claimed}
    assert sum(job.id in claimed_ids for job in pending_jobs) == 1
    assert sum(job.status == JOB_STATUS_PENDING for job in pending_jobs) == 3
