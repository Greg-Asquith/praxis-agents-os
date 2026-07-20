"""Periodically refresh provider resources and permission metadata."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.integrations import IntegrationConnection, IntegrationDiscoveryRun
from models.jobs import Job
from services.integrations.discovery.enqueue_discovery import enqueue_discovery
from services.integrations.manifest import PROVIDER_MANIFESTS

REDISCOVER_STALE_KIND = "integrations.rediscover_stale"
ELIGIBLE_STATUSES = frozenset({"active", "needs_resource_selection", "degraded"})


async def rediscover_stale(db: AsyncSession, *, job: Job) -> None:
    """Enqueue stale discoverable connections and schedule the next scan."""
    from services.jobs.enqueue_job import enqueue_job

    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=settings.INTEGRATIONS_REDISCOVERY_INTERVAL_SECONDS)
    latest_success = (
        select(
            IntegrationDiscoveryRun.connection_id,
            func.max(IntegrationDiscoveryRun.finished_at).label("finished_at"),
        )
        .where(IntegrationDiscoveryRun.status == "succeeded")
        .group_by(IntegrationDiscoveryRun.connection_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(IntegrationConnection, latest_success.c.finished_at)
            .outerjoin(
                latest_success,
                latest_success.c.connection_id == IntegrationConnection.id,
            )
            .where(
                IntegrationConnection.deleted.is_(False),
                IntegrationConnection.status.in_(ELIGIBLE_STATUSES),
            )
        )
    ).all()
    for connection, finished_at in rows:
        manifest = PROVIDER_MANIFESTS.get(connection.provider_key)
        if (
            manifest is not None
            and manifest.requires_discovery
            and (finished_at is None or finished_at < cutoff)
        ):
            await enqueue_discovery(db, connection=connection)

    await enqueue_job(
        db,
        kind=REDISCOVER_STALE_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"integrations-rediscover:{job.id}",
        run_after=now + timedelta(seconds=settings.INTEGRATIONS_REDISCOVERY_INTERVAL_SECONDS),
    )


async def ensure_integrations_rediscover_job(db: AsyncSession) -> Job:
    """Ensure a periodic integration re-discovery scan is pending or running."""
    from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
    from services.jobs.enqueue_job import enqueue_job

    existing = await db.scalar(
        select(Job).where(
            Job.kind == REDISCOVER_STALE_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing
    return await enqueue_job(
        db,
        kind=REDISCOVER_STALE_KIND,
        content_hash="integrations-rediscover:ensure",
        run_after=datetime.now(UTC),
    )
