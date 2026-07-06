# apps/api/services/jobs/enqueue_job.py

"""Enqueue a generic background job."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.registry import get_job_handler
from services.jobs.utils import compute_content_hash, is_jobs_in_flight_integrity_error


async def enqueue_job(
    db: AsyncSession,
    *,
    kind: str,
    workspace_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    payload: dict[str, object] | None = None,
    content_hash: str | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
    initiated_by_user_id: UUID | None = None,
) -> Job:
    """Enqueue a registered job, returning an existing in-flight duplicate when present."""
    handler = get_job_handler(kind)
    if handler is None:
        raise AppValidationError(
            "Unknown job kind",
            field="kind",
            details={"kind": kind},
        )

    normalized_payload = payload or {}
    normalized_hash = content_hash or compute_content_hash(normalized_payload)
    if max_attempts is not None and max_attempts <= 0:
        raise AppValidationError(
            "max_attempts must be greater than zero",
            field="max_attempts",
            details={"max_attempts": max_attempts},
        )
    attempts_limit = (
        max_attempts
        if max_attempts is not None
        else handler.max_attempts or settings.JOBS_DEFAULT_MAX_ATTEMPTS
    )
    scheduled_at = run_after or datetime.now(UTC)

    job = Job(
        kind=kind,
        workspace_id=workspace_id,
        subject_type=subject_type,
        subject_id=subject_id,
        content_hash=normalized_hash,
        payload=normalized_payload,
        priority=priority,
        run_after=scheduled_at,
        max_attempts=attempts_limit,
        initiated_by_user_id=initiated_by_user_id,
    )

    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError as exc:
        if not is_jobs_in_flight_integrity_error(exc):
            raise
        existing = await _get_existing_in_flight_job(
            db,
            kind=kind,
            workspace_id=workspace_id,
            subject_type=subject_type,
            subject_id=subject_id,
            content_hash=normalized_hash,
        )
        if existing is None:
            raise
        return existing

    return job


async def _get_existing_in_flight_job(
    db: AsyncSession,
    *,
    kind: str,
    workspace_id: UUID | None,
    subject_type: str | None,
    subject_id: UUID | None,
    content_hash: str,
) -> Job | None:
    stmt = select(Job).where(
        Job.kind == kind,
        Job.content_hash == content_hash,
        Job.status.in_(IN_FLIGHT_JOB_STATUSES),
    )
    if workspace_id is None:
        stmt = stmt.where(Job.workspace_id.is_(None))
    else:
        stmt = stmt.where(Job.workspace_id == workspace_id)
    if subject_type is None:
        stmt = stmt.where(Job.subject_type.is_(None))
    else:
        stmt = stmt.where(Job.subject_type == subject_type)
    if subject_id is None:
        stmt = stmt.where(Job.subject_id.is_(None))
    else:
        stmt = stmt.where(Job.subject_id == subject_id)
    return await db.scalar(stmt)
