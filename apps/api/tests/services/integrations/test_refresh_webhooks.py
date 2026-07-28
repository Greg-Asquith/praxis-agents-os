"""Webhook refresh scheduling behavior."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.integrations.events.domain import REFRESH_WEBHOOKS_KIND
from services.integrations.events.refresh_webhooks import refresh_webhooks


async def test_refresh_webhooks_schedules_a_bounded_dedup_key(
    db_session: AsyncSession,
) -> None:
    current = Job(
        kind=REFRESH_WEBHOOKS_KIND,
        content_hash="integrations-refresh-webhooks:ensure",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    db_session.add(current)
    await db_session.flush()

    await refresh_webhooks(db_session, job=current)

    scheduled = await db_session.scalar(
        select(Job).where(
            Job.kind == REFRESH_WEBHOOKS_KIND,
            Job.id != current.id,
            Job.payload["scheduled_by_job_id"].astext == str(current.id),
        )
    )
    assert scheduled is not None
    assert len(scheduled.content_hash) == 64
