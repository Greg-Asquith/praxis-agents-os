# apps/api/services/jobs/handlers/retention.py

"""Shared bounded-delete primitives for event-retention handlers."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.audit_event import AuditEvent
from models.jobs import Job
from models.security import SecurityEvent
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES

EventModel = type[AuditEvent] | type[SecurityEvent]


@dataclass(frozen=True)
class EventRetentionSweepResult:
    """Summary of one bounded event-retention sweep."""

    deleted_count: int
    has_more: bool


async def sweep_expired_event_rows(
    db: AsyncSession,
    *,
    model: EventModel,
    cutoff: datetime,
    batch_size: int,
    run_limit: int,
) -> EventRetentionSweepResult:
    """Delete expired rows in ordered batches without exceeding one run's cap."""
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if run_limit <= 0:
        raise ValueError("run_limit must be greater than zero")

    deleted_count = 0
    while deleted_count < run_limit:
        current_batch_size = min(batch_size, run_limit - deleted_count)
        expired_ids = (
            select(model.id)
            .where(model.created_at < cutoff)
            .order_by(model.created_at, model.id)
            .limit(current_batch_size)
        )
        deleted_ids = (
            await db.scalars(delete(model).where(model.id.in_(expired_ids)).returning(model.id))
        ).all()
        batch_count = len(deleted_ids)
        deleted_count += batch_count
        if batch_count < current_batch_size:
            return EventRetentionSweepResult(deleted_count=deleted_count, has_more=False)

    has_more = (
        await db.scalar(select(model.id).where(model.created_at < cutoff).limit(1)) is not None
    )
    return EventRetentionSweepResult(deleted_count=deleted_count, has_more=has_more)


async def ensure_event_retention_sweep_job(
    db: AsyncSession,
    *,
    kind: str,
    content_hash: str,
) -> Job:
    """Ensure one pending or running retention sweep exists for a job kind."""
    existing = await db.scalar(
        select(Job).where(
            Job.kind == kind,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(db, kind=kind, content_hash=content_hash)


async def finish_event_retention_sweep(
    db: AsyncSession,
    *,
    job: Job,
    kind: str,
    content_hash_prefix: str,
    now: datetime,
    result: EventRetentionSweepResult,
) -> Job:
    """Persist the result summary and enqueue an immediate or periodic successor."""
    job.payload = {
        **job.payload,
        "result": {
            "deleted_count": result.deleted_count,
            "has_more": result.has_more,
        },
    }

    from services.jobs.enqueue_job import enqueue_job

    run_after = (
        now if result.has_more else now + timedelta(seconds=settings.JOBS_SWEEP_INTERVAL_SECONDS)
    )
    return await enqueue_job(
        db,
        kind=kind,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"{content_hash_prefix}:{job.id}",
        run_after=run_after,
    )
