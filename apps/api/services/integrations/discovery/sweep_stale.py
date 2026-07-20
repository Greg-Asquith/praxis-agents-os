# apps/api/services/integrations/discovery/sweep_stale.py

"""Enforce integration resource and credential retention windows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.integrations import (
    ExternalCredential,
    IntegrationConnection,
    IntegrationDiscoveryRun,
    IntegrationOAuthState,
    IntegrationResource,
)
from models.jobs import Job

SWEEP_STALE_KIND = "integrations.sweep_stale"
AUTH_PENDING_RETENTION_DAYS = 7


async def sweep_stale(db: AsyncSession, *, job: Job) -> None:
    """Hard-delete expired integration lifecycle rows and schedule the next sweep."""
    from services.jobs.enqueue_job import enqueue_job

    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=settings.INTEGRATIONS_STALE_RETENTION_DAYS)
    revoked_cutoff = now - timedelta(days=settings.INTEGRATIONS_REVOKED_RETENTION_DAYS)
    auth_pending_cutoff = now - timedelta(days=AUTH_PENDING_RETENTION_DAYS)

    await db.execute(
        delete(IntegrationDiscoveryRun).where(IntegrationDiscoveryRun.created_at < stale_cutoff)
    )
    await db.execute(
        delete(IntegrationResource).where(
            or_(
                IntegrationResource.removed_at < stale_cutoff,
                IntegrationResource.deleted_at < stale_cutoff,
            )
        )
    )
    await db.execute(delete(IntegrationOAuthState).where(IntegrationOAuthState.expires_at < now))

    stale_connection_credential_ids = list(
        (
            await db.scalars(
                select(IntegrationConnection.credential_id)
                .join(
                    ExternalCredential,
                    ExternalCredential.id == IntegrationConnection.credential_id,
                )
                .where(
                    or_(
                        (
                            (ExternalCredential.revoked_at < revoked_cutoff)
                            & or_(
                                IntegrationConnection.status == "revoked",
                                IntegrationConnection.deleted.is_(True),
                            )
                        ),
                        (
                            (IntegrationConnection.status == "auth_pending")
                            & (IntegrationConnection.created_at < auth_pending_cutoff)
                        ),
                    )
                )
            )
        ).all()
    )
    if stale_connection_credential_ids:
        await db.execute(
            delete(IntegrationConnection).where(
                IntegrationConnection.credential_id.in_(stale_connection_credential_ids)
            )
        )
        await db.execute(
            delete(ExternalCredential).where(
                ExternalCredential.id.in_(stale_connection_credential_ids)
            )
        )

    await db.execute(
        delete(ExternalCredential).where(
            ExternalCredential.revoked_at < revoked_cutoff,
            ~ExternalCredential.id.in_(
                select(IntegrationConnection.credential_id).where(
                    IntegrationConnection.credential_id == ExternalCredential.id
                )
            ),
        )
    )
    await enqueue_job(
        db,
        kind=SWEEP_STALE_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"integrations-sweep:{job.id}",
        run_after=now + timedelta(seconds=settings.INTEGRATIONS_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_integrations_sweep_job(db: AsyncSession) -> Job:
    """Ensure an integration retention sweep is pending or running."""
    from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
    from services.jobs.enqueue_job import enqueue_job

    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_STALE_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing
    return await enqueue_job(
        db,
        kind=SWEEP_STALE_KIND,
        content_hash="integrations-sweep:ensure",
        run_after=datetime.now(UTC),
    )
