# apps/api/tests/services/jobs/test_sweep_terminal_jobs.py

"""Tests for the built-in terminal jobs sweeper."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.artifacts.domain import CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND
from services.jobs.domain import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from services.jobs.handlers.sweep_terminal_jobs import ensure_sweep_job, sweep_terminal_jobs
from tests.factories import build_job

pytestmark = pytest.mark.asyncio


async def test_sweep_terminal_jobs_deletes_old_terminal_and_keeps_others(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(delete(Job))
    await db_session.flush()
    old_terminal = build_job(status=JOB_STATUS_FAILED, payload={"old": True})
    old_terminal.finished_at = datetime.now(UTC) - timedelta(days=31)
    fresh_terminal = build_job(status=JOB_STATUS_FAILED, payload={"fresh": True})
    fresh_terminal.finished_at = datetime.now(UTC)
    running = build_job(status=JOB_STATUS_RUNNING, payload={"running": True})
    current = build_job(status=JOB_STATUS_RUNNING, payload={"current": True})
    db_session.add_all([old_terminal, fresh_terminal, running, current])
    await db_session.flush()

    await sweep_terminal_jobs(db_session, current)

    remaining_ids = set(await db_session.scalars(select(Job.id)))
    assert old_terminal.id not in remaining_ids
    assert fresh_terminal.id in remaining_ids
    assert running.id in remaining_ids
    assert current.id in remaining_ids
    pending_jobs = (
        await db_session.scalars(
            select(Job).where(
                Job.status == JOB_STATUS_PENDING,
                Job.content_hash == f"sweep-terminal:{current.id}",
            )
        )
    ).all()
    assert len(pending_jobs) == 1


async def test_ensure_sweep_job_is_idempotent(db_session: AsyncSession) -> None:
    await db_session.execute(delete(Job))
    await db_session.flush()
    first = await ensure_sweep_job(db_session)
    second = await ensure_sweep_job(db_session)

    assert second.id == first.id


async def test_terminal_retention_preserves_unfinished_artifact_cleanup(
    db_session: AsyncSession,
) -> None:
    cleanup_jobs = [
        build_job(kind=CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND, status=status)
        for status in (JOB_STATUS_FAILED, JOB_STATUS_CANCELLED, JOB_STATUS_SUCCEEDED)
    ]
    unrelated = build_job(kind="test.unrelated", status=JOB_STATUS_FAILED)
    current = build_job(status=JOB_STATUS_RUNNING)
    for job in [*cleanup_jobs, unrelated]:
        job.finished_at = datetime.now(UTC) - timedelta(days=31)
    db_session.add_all([*cleanup_jobs, unrelated, current])
    await db_session.flush()

    await sweep_terminal_jobs(db_session, current)

    tested_ids = {job.id for job in [*cleanup_jobs, unrelated]}
    remaining = set(await db_session.scalars(select(Job.id).where(Job.id.in_(tested_ids))))
    assert remaining == {cleanup_jobs[0].id, cleanup_jobs[1].id}
