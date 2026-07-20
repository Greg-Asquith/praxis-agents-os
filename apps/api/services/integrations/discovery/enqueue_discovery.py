"""Enqueue resource discovery for an integration connection."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection
from models.jobs import Job
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.domain import CONNECTION_STATUS_DISCOVERY_PENDING

DISCOVER_RESOURCES_KIND = "integrations.discover_resources"


async def enqueue_discovery(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
) -> Job:
    """Enqueue one deduplicated resource-discovery job for a connection."""
    from services.jobs.enqueue_job import enqueue_job

    if connection.status != CONNECTION_STATUS_DISCOVERY_PENDING:
        await transition_connection_status(
            db,
            connection,
            CONNECTION_STATUS_DISCOVERY_PENDING,
            reason="resource_discovery_queued",
        )
    return await enqueue_job(
        db,
        kind=DISCOVER_RESOURCES_KIND,
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        payload={},
        # Discovery owns its final-failure notification; an initiator would
        # also trigger the generic job_failed notification.
        initiated_by_user_id=None,
    )
