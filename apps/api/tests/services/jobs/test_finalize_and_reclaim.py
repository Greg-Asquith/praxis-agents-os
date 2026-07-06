# apps/api/tests/services/jobs/test_finalize_and_reclaim.py

"""Tests for generic job finalization and stale reclaim."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from services.jobs.domain import JOB_STATUS_FAILED, JOB_STATUS_PENDING, JOB_STATUS_RUNNING
from services.jobs.finalize_job import finalize_job_failure, finalize_job_success
from services.jobs.reclaim_stale_jobs import reclaim_stale_jobs
from tests.factories import build_job, build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def test_retryable_failure_requeues_with_backoff(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr("services.jobs.finalize_job.retry_backoff", lambda _attempts: 45.0)
    job = build_job(status=JOB_STATUS_RUNNING, attempts=1, max_attempts=3)
    db_session.add(job)
    await db_session.flush()

    terminal = await finalize_job_failure(
        db_session, job, code="boom", message=" exploded ", now=now
    )

    assert terminal is False
    assert job.status == JOB_STATUS_PENDING
    assert job.run_after == now + timedelta(seconds=45)
    assert job.locked_by is None
    assert job.last_error_message == "exploded"


async def test_final_failure_creates_notification_for_initiator(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"job-notify-{uuid4().hex[:8]}")
    user = build_user(email=f"job-notify-{uuid4().hex}@example.com")
    db_session.add_all([workspace, user])
    await db_session.flush()
    job = build_job(
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        status=JOB_STATUS_RUNNING,
        attempts=2,
        max_attempts=2,
    )
    db_session.add(job)
    await db_session.flush()

    terminal = await finalize_job_failure(db_session, job, code="final", message="done")

    assert terminal is True
    assert job.status == JOB_STATUS_FAILED
    note = await db_session.scalar(select(Notification).where(Notification.source == "jobs"))
    assert note is not None
    assert note.recipient_user_id == user.id
    assert note.workspace_id == workspace.id


async def test_final_failure_without_initiator_does_not_notify(db_session: AsyncSession) -> None:
    job = build_job(status=JOB_STATUS_RUNNING, attempts=1, max_attempts=1)
    db_session.add(job)
    await db_session.flush()

    terminal = await finalize_job_failure(db_session, job, code="final", message="done")

    assert terminal is True
    assert job.status == JOB_STATUS_FAILED
    note = await db_session.scalar(select(Notification).where(Notification.source == "jobs"))
    assert note is None


async def test_success_clears_lock_and_errors(db_session: AsyncSession) -> None:
    job = build_job(status=JOB_STATUS_RUNNING)
    job.locked_by = "worker"
    job.locked_at = datetime.now(UTC)
    job.lock_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    job.last_error_code = "old"
    job.last_error_message = "old error"
    db_session.add(job)
    await db_session.flush()

    await finalize_job_success(db_session, job)

    assert job.status == "succeeded"
    assert job.locked_by is None
    assert job.last_error_code is None
    assert job.finished_at is not None


async def test_reclaim_stale_jobs_only_reclaims_expired(db_session: AsyncSession) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    expired = build_job(status=JOB_STATUS_RUNNING)
    expired.lock_expires_at = now - timedelta(seconds=1)
    fresh = build_job(status=JOB_STATUS_RUNNING, payload={"fresh": True})
    fresh.lock_expires_at = now + timedelta(seconds=1)
    db_session.add_all([expired, fresh])
    await db_session.flush()

    count = await reclaim_stale_jobs(db_session, now=now)

    assert count == 1
    await db_session.refresh(expired)
    await db_session.refresh(fresh)
    assert expired.status == JOB_STATUS_PENDING
    assert expired.last_error_code == "lease_expired"
    assert fresh.status == JOB_STATUS_RUNNING


async def test_reclaim_stale_jobs_fails_terminal_when_attempts_exhausted(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    workspace = build_workspace(slug=f"job-reclaim-notify-{uuid4().hex[:8]}")
    user = build_user(email=f"job-reclaim-notify-{uuid4().hex}@example.com")
    db_session.add_all([workspace, user])
    await db_session.flush()
    exhausted = build_job(
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        status=JOB_STATUS_RUNNING,
        attempts=2,
        max_attempts=2,
    )
    exhausted.locked_by = "dead-worker"
    exhausted.lock_expires_at = now - timedelta(seconds=1)
    db_session.add(exhausted)
    await db_session.flush()

    count = await reclaim_stale_jobs(db_session, now=now)

    assert count == 1
    await db_session.refresh(exhausted)
    assert exhausted.status == JOB_STATUS_FAILED
    assert exhausted.last_error_code == "lease_expired"
    note = await db_session.scalar(select(Notification).where(Notification.source == "jobs"))
    assert note is not None
    assert note.recipient_user_id == user.id
