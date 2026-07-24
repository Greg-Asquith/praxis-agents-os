# apps/api/services/integrations/discovery/handlers.py

"""Generic-job handlers for integration discovery lifecycle work."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from models.integrations import IntegrationConnection, IntegrationDiscoveryRun
from models.jobs import Job
from services.audit_events import AuditStatus
from services.integrations.connections.notify_connection_event import (
    notify_connection_event,
)
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.discovery.enqueue_discovery import DISCOVER_RESOURCES_KIND
from services.integrations.discovery.rediscover_stale import (
    REDISCOVER_STALE_KIND,
    rediscover_stale,
)
from services.integrations.discovery.run_discovery import run_discovery
from services.integrations.discovery.sweep_stale import SWEEP_STALE_KIND, sweep_stale
from services.integrations.domain import CONNECTION_STATUS_DISCOVERY_PENDING
from services.jobs.registry import job_handler


@job_handler(
    kind=DISCOVER_RESOURCES_KIND,
    timeout=settings.INTEGRATIONS_DISCOVERY_TIMEOUT_SECONDS,
)
async def discover_resources(db: AsyncSession, job: Job) -> None:
    job_id = job.id
    subject_id = job.subject_id
    is_final_attempt = job.attempts >= job.max_attempts
    try:
        if subject_id is None:
            raise ValueError("Integration discovery job requires a connection subject")
        await run_discovery(db, connection_id=subject_id, job_id=job_id)
    except asyncio.CancelledError:
        await db.rollback()
        if subject_id is not None:
            await _record_discovery_timeout(
                db,
                connection_id=subject_id,
                job_id=job_id,
                notify=is_final_attempt,
            )
            await db.commit()
        raise
    except IntegrationAuthError:
        raise
    except Exception as exc:
        if subject_id is not None and is_final_attempt:
            await _settle_terminal_discovery_failure(
                db,
                connection_id=subject_id,
                job_id=job_id,
                error=exc,
            )
            await notify_connection_event(
                db,
                connection_id=subject_id,
                event="discovery_failed",
            )
            await db.commit()
        raise


@job_handler(kind=SWEEP_STALE_KIND, timeout=120.0)
async def sweep_stale_handler(db: AsyncSession, job: Job) -> None:
    await sweep_stale(db, job=job)


@job_handler(kind=REDISCOVER_STALE_KIND, timeout=120.0)
async def rediscover_stale_handler(db: AsyncSession, job: Job) -> None:
    await rediscover_stale(db, job=job)


async def _record_discovery_timeout(
    db: AsyncSession,
    *,
    connection_id: UUID,
    job_id: UUID,
    notify: bool,
) -> None:
    """Persist lifecycle state before the worker records a timed-out attempt."""
    connection = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.deleted.is_(False),
        )
    )
    if connection is None:
        return

    prior_success = await db.scalar(
        select(IntegrationDiscoveryRun.id)
        .where(
            IntegrationDiscoveryRun.connection_id == connection.id,
            IntegrationDiscoveryRun.status == "succeeded",
        )
        .limit(1)
    )
    now = datetime.now(UTC)
    db.add(
        IntegrationDiscoveryRun(
            connection_id=connection.id,
            job_id=job_id,
            status="failed",
            error_code="handler_timeout",
            error_message="Provider discovery exceeded its execution timeout",
            started_at=now,
            finished_at=now,
        )
    )
    if connection.status == CONNECTION_STATUS_DISCOVERY_PENDING:
        await transition_connection_status(
            db,
            connection,
            "degraded" if prior_success is not None else "error",
            reason="resource_discovery_timed_out",
            audit_status=AuditStatus.FAILURE,
        )
    if notify:
        await notify_connection_event(
            db,
            connection_id=connection.id,
            event="discovery_failed",
        )


async def _settle_terminal_discovery_failure(
    db: AsyncSession,
    *,
    connection_id: UUID,
    job_id: UUID,
    error: Exception,
) -> None:
    """Ensure a terminal job cannot leave its connection looking in flight."""
    connection = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.deleted.is_(False),
        )
    )
    if connection is None or connection.status != CONNECTION_STATUS_DISCOVERY_PENDING:
        return

    prior_success = await db.scalar(
        select(IntegrationDiscoveryRun.id)
        .where(
            IntegrationDiscoveryRun.connection_id == connection.id,
            IntegrationDiscoveryRun.status == "succeeded",
        )
        .limit(1)
    )
    existing_run = await db.scalar(
        select(IntegrationDiscoveryRun).where(IntegrationDiscoveryRun.job_id == job_id).limit(1)
    )
    now = datetime.now(UTC)
    if existing_run is None:
        db.add(
            IntegrationDiscoveryRun(
                connection_id=connection.id,
                job_id=job_id,
                status="failed",
                error_code=error.__class__.__name__[:64],
                error_message=(str(error) or error.__class__.__name__)[:1000],
                started_at=now,
                finished_at=now,
            )
        )
    elif existing_run.status == "running":
        existing_run.status = "failed"
        existing_run.error_code = error.__class__.__name__[:64]
        existing_run.error_message = (str(error) or error.__class__.__name__)[:1000]
        existing_run.finished_at = now

    await transition_connection_status(
        db,
        connection,
        "degraded" if prior_success is not None else "error",
        reason="resource_discovery_failed",
        audit_status=AuditStatus.FAILURE,
    )
