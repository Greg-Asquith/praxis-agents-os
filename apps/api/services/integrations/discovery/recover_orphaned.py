# apps/api/services/integrations/discovery/recover_orphaned.py

"""Recover discovery-pending connections that have no executable job."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection
from models.jobs import Job
from services.integrations.discovery.enqueue_discovery import (
    DISCOVER_RESOURCES_KIND,
    enqueue_discovery,
)
from services.integrations.domain import CONNECTION_STATUS_DISCOVERY_PENDING
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES


async def recover_orphaned_discoveries(db: AsyncSession) -> int:
    """Re-enqueue connections whose pending status is not backed by work."""
    in_flight_job = exists(
        select(Job.id).where(
            Job.kind == DISCOVER_RESOURCES_KIND,
            Job.subject_id == IntegrationConnection.id,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    connections = list(
        (
            await db.scalars(
                select(IntegrationConnection).where(
                    IntegrationConnection.deleted.is_(False),
                    IntegrationConnection.status == CONNECTION_STATUS_DISCOVERY_PENDING,
                    ~in_flight_job,
                )
            )
        ).all()
    )
    for connection in connections:
        await enqueue_discovery(db, connection=connection)
    return len(connections)
