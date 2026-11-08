# apps/api/services/jobs/enqueue_job.py

"""Enqueue a generic background job."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.jobs import Job
from services.jobs.domain import JOB_STATUS_PENDING
from services.jobs.registry import get_job_handler
from services.jobs.utils import (
    compute_content_hash,
    is_pending_job_duplicate_error,
    normalize_content_hash,
)


async def enqueue_job(
    db: AsyncSession,
    *,
    kind: str,
    workspace_id: UUID | None = None,
    concurrency_user_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    payload: dict[str, object] | None = None,
    content_hash: str | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
    initiated_by_user_id: UUID | None = None,
) -> Job:
    """Enqueue a registered job, returning an existing pending duplicate when present."""
    handler = get_job_handler(kind)
    if handler is None:
        raise AppValidationError(
            "Unknown job kind",
            field="kind",
            details={"kind": kind},
        )

    normalized_payload = payload or {}
    if workspace_id is not None and concurrency_user_id is not None:
        raise AppValidationError(
            "Jobs cannot have both workspace and user concurrency owners",
            field="concurrency_user_id",
        )
    normalized_hash = normalize_content_hash(
        content_hash or compute_content_hash(normalized_payload)
    )
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
        concurrency_user_id=concurrency_user_id,
        subject_type=subject_type,
        subject_id=subject_id,
        content_hash=normalized_hash,
        payload=normalized_payload,
        priority=priority,
        run_after=scheduled_at,
        max_attempts=attempts_limit,
        initiated_by_user_id=initiated_by_user_id,
    )

    # A worker can claim the pending twin between the failed insert and the read; insert again.
    saved = await _insert_or_get_pending(db, job) or await _insert_or_get_pending(db, job)
    if saved is None:
        raise ConflictError("Duplicate job is already being claimed", conflicting_resource="job")
    return saved


async def _insert_or_get_pending(db: AsyncSession, job: Job) -> Job | None:
    """Insert the job, or return its pending duplicate; None when the duplicate just left."""
    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError as exc:
        if not is_pending_job_duplicate_error(exc):
            raise
        return await _get_pending_duplicate(
            db,
            kind=job.kind,
            workspace_id=job.workspace_id,
            concurrency_user_id=job.concurrency_user_id,
            subject_type=job.subject_type,
            subject_id=job.subject_id,
            content_hash=job.content_hash,
        )
    return job


async def _get_pending_duplicate(
    db: AsyncSession,
    *,
    kind: str,
    workspace_id: UUID | None,
    concurrency_user_id: UUID | None,
    subject_type: str | None,
    subject_id: UUID | None,
    content_hash: str,
) -> Job | None:
    stmt = select(Job).where(
        Job.kind == kind,
        Job.content_hash == content_hash,
        Job.status == JOB_STATUS_PENDING,
    )
    if workspace_id is None:
        stmt = stmt.where(Job.workspace_id.is_(None))
    else:
        stmt = stmt.where(Job.workspace_id == workspace_id)
    if concurrency_user_id is None:
        stmt = stmt.where(Job.concurrency_user_id.is_(None))
    else:
        stmt = stmt.where(Job.concurrency_user_id == concurrency_user_id)
    if subject_type is None:
        stmt = stmt.where(Job.subject_type.is_(None))
    else:
        stmt = stmt.where(Job.subject_type == subject_type)
    if subject_id is None:
        stmt = stmt.where(Job.subject_id.is_(None))
    else:
        stmt = stmt.where(Job.subject_id == subject_id)
    return await db.scalar(stmt)
