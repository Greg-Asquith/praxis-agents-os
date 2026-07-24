# apps/api/services/integrations/events/refresh_webhooks.py

"""Refresh expiring provider webhooks on the generic jobs harness."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.integrations import IntegrationWebhook
from models.jobs import Job
from services.integrations.events.domain import REFRESH_WEBHOOKS_KIND
from services.integrations.plugin import PROVIDER_PLUGINS


async def refresh_webhooks(db: AsyncSession, *, job: Job) -> None:
    """Refresh due active registrations and schedule the next scan."""
    from services.jobs.enqueue_job import enqueue_job

    now = datetime.now(UTC)
    refresh_before = now + timedelta(seconds=settings.INTEGRATIONS_WEBHOOK_REFRESH_MARGIN_SECONDS)
    webhooks = (
        await db.scalars(
            select(IntegrationWebhook)
            .where(
                IntegrationWebhook.status == "active",
                IntegrationWebhook.expires_at.is_not(None),
                IntegrationWebhook.expires_at <= refresh_before,
            )
            .order_by(IntegrationWebhook.expires_at.asc())
            .with_for_update(skip_locked=True)
        )
    ).all()
    for webhook in webhooks:
        plugin = PROVIDER_PLUGINS.get(webhook.provider_key)
        if plugin is None or plugin.event_definition is None:
            continue
        await plugin.event_definition.refresh_webhook(db, webhook)
    await enqueue_job(
        db,
        kind=REFRESH_WEBHOOKS_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        run_after=now + timedelta(seconds=settings.INTEGRATIONS_WEBHOOK_REFRESH_INTERVAL_SECONDS),
    )


async def ensure_refresh_webhooks_job(db: AsyncSession) -> Job:
    """Ensure one webhook refresh scan is pending or running."""
    from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
    from services.jobs.enqueue_job import enqueue_job

    existing = await db.scalar(
        select(Job).where(
            Job.kind == REFRESH_WEBHOOKS_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing
    return await enqueue_job(
        db,
        kind=REFRESH_WEBHOOKS_KIND,
        content_hash="integrations-refresh-webhooks:ensure",
        run_after=datetime.now(UTC),
    )
