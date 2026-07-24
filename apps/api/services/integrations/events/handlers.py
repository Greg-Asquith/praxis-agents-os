# apps/api/services/integrations/events/handlers.py

"""Generic-job handlers for inbound integration events."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.integrations.events.domain import PROCESS_EVENT_KIND, REFRESH_WEBHOOKS_KIND
from services.integrations.events.process_event import process_event
from services.integrations.events.refresh_webhooks import refresh_webhooks
from services.jobs.registry import job_handler


@job_handler(
    kind=PROCESS_EVENT_KIND,
    timeout=settings.INTEGRATIONS_EVENT_PROCESS_TIMEOUT_SECONDS,
)
async def process_event_handler(db: AsyncSession, job: Job) -> None:
    if job.subject_id is None:
        raise ValueError("Integration event job requires an event subject")
    await process_event(db, event_id=job.subject_id)


@job_handler(kind=REFRESH_WEBHOOKS_KIND, timeout=120.0)
async def refresh_webhooks_handler(db: AsyncSession, job: Job) -> None:
    await refresh_webhooks(db, job=job)
