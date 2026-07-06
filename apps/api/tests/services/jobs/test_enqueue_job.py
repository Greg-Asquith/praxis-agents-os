# apps/api/tests/services/jobs/test_enqueue_job.py

"""Tests for generic job enqueueing."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from services.jobs.domain import JOB_STATUS_FAILED, JOB_STATUS_PENDING
from services.jobs.enqueue_job import enqueue_job
from tests.factories import build_job, build_workspace

pytestmark = pytest.mark.asyncio


async def test_enqueue_job_rejects_unknown_kind(db_session: AsyncSession) -> None:
    with pytest.raises(AppValidationError):
        await enqueue_job(db_session, kind="missing.kind")


async def test_enqueue_job_returns_existing_in_flight_duplicate(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"job-dedup-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()

    first = await enqueue_job(
        db_session,
        kind="jobs.sweep_terminal",
        workspace_id=workspace.id,
        subject_type="file",
        subject_id=uuid4(),
        payload={"b": 2, "a": 1},
    )
    second = await enqueue_job(
        db_session,
        kind="jobs.sweep_terminal",
        workspace_id=workspace.id,
        subject_type=first.subject_type,
        subject_id=first.subject_id,
        payload={"a": 1, "b": 2},
    )

    assert second.id == first.id


async def test_enqueue_job_dedup_is_scoped_to_workspace(
    db_session: AsyncSession,
) -> None:
    first_workspace = build_workspace(slug=f"job-dedup-a-{uuid4().hex[:8]}")
    second_workspace = build_workspace(slug=f"job-dedup-b-{uuid4().hex[:8]}")
    db_session.add_all([first_workspace, second_workspace])
    await db_session.flush()
    subject_id = uuid4()
    payload = {"same": True}

    first = await enqueue_job(
        db_session,
        kind="jobs.sweep_terminal",
        workspace_id=first_workspace.id,
        subject_type="file",
        subject_id=subject_id,
        payload=payload,
    )
    second = await enqueue_job(
        db_session,
        kind="jobs.sweep_terminal",
        workspace_id=second_workspace.id,
        subject_type="file",
        subject_id=subject_id,
        payload=payload,
    )

    assert second.id != first.id
    assert second.workspace_id == second_workspace.id


async def test_terminal_job_does_not_block_reenqueue(db_session: AsyncSession) -> None:
    existing = build_job(
        kind="jobs.sweep_terminal",
        status=JOB_STATUS_FAILED,
        payload={"same": True},
    )
    existing.finished_at = datetime.now(UTC)
    db_session.add(existing)
    await db_session.flush()

    created = await enqueue_job(
        db_session,
        kind="jobs.sweep_terminal",
        payload={"same": True},
    )

    assert created.id != existing.id
    assert created.status == JOB_STATUS_PENDING


async def test_null_subject_jobs_dedup_against_each_other(db_session: AsyncSession) -> None:
    first = await enqueue_job(db_session, kind="jobs.sweep_terminal", payload={"x": 1})
    second = await enqueue_job(db_session, kind="jobs.sweep_terminal", payload={"x": 1})

    assert second.id == first.id


async def test_enqueue_uses_default_max_attempts(db_session: AsyncSession) -> None:
    job = await enqueue_job(db_session, kind="jobs.sweep_terminal")

    assert job.max_attempts == 5


async def test_enqueue_rejects_invalid_max_attempts(db_session: AsyncSession) -> None:
    with pytest.raises(AppValidationError, match="max_attempts"):
        await enqueue_job(db_session, kind="jobs.sweep_terminal", max_attempts=0)


async def test_jobs_table_rejects_invalid_max_attempts(db_session: AsyncSession) -> None:
    db_session.add(build_job(max_attempts=0, payload={"invalid": True}))

    with pytest.raises(IntegrityError):
        await db_session.flush()
