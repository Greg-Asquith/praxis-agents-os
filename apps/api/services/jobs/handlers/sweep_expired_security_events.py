# apps/api/services/jobs/handlers/sweep_expired_security_events.py

"""Retention sweeper for append-only security event rows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from models.security import SecurityEvent
from services.jobs.handlers.retention import (
    EventRetentionSweepResult,
    ensure_event_retention_sweep_job,
    finish_event_retention_sweep,
    sweep_expired_event_rows,
)
from services.jobs.registry import job_handler

SWEEP_EXPIRED_SECURITY_EVENTS_KIND = "security_events.sweep_expired"
DEFAULT_SECURITY_EVENT_SWEEP_BATCH_SIZE = 100
DEFAULT_SECURITY_EVENT_SWEEP_RUN_LIMIT = 1_000


@job_handler(kind=SWEEP_EXPIRED_SECURITY_EVENTS_KIND, timeout=120.0)
async def handle_sweep_expired_security_events(db: AsyncSession, job: Job) -> None:
    """Delete one bounded run of expired security events and schedule its successor."""
    now = datetime.now(UTC)
    result = await sweep_expired_security_events(
        db,
        now=now,
        batch_size=DEFAULT_SECURITY_EVENT_SWEEP_BATCH_SIZE,
        run_limit=DEFAULT_SECURITY_EVENT_SWEEP_RUN_LIMIT,
    )
    await finish_event_retention_sweep(
        db,
        job=job,
        kind=SWEEP_EXPIRED_SECURITY_EVENTS_KIND,
        content_hash_prefix="sweep-security-events",
        now=now,
        result=result,
    )


async def sweep_expired_security_events(
    db: AsyncSession,
    *,
    now: datetime,
    retention_days: int | None = None,
    batch_size: int = DEFAULT_SECURITY_EVENT_SWEEP_BATCH_SIZE,
    run_limit: int = DEFAULT_SECURITY_EVENT_SWEEP_RUN_LIMIT,
) -> EventRetentionSweepResult:
    """Delete security events strictly older than the configured cutoff."""
    configured_days = (
        settings.SECURITY_EVENTS_RETENTION_DAYS if retention_days is None else retention_days
    )
    if configured_days <= 0:
        raise ValueError("retention_days must be greater than zero")
    cutoff = now - timedelta(days=configured_days)
    return await sweep_expired_event_rows(
        db,
        model=SecurityEvent,
        cutoff=cutoff,
        batch_size=batch_size,
        run_limit=run_limit,
    )


async def ensure_security_event_sweep_job(db: AsyncSession) -> Job:
    """Ensure at least one security-event retention sweep is pending or running."""
    return await ensure_event_retention_sweep_job(
        db,
        kind=SWEEP_EXPIRED_SECURITY_EVENTS_KIND,
        content_hash="sweep-security-events:ensure",
    )
