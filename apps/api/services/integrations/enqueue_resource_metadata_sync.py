# apps/api/services/integrations/enqueue_resource_metadata_sync.py

"""Enqueue provider-declared metadata synchronization for one resource."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection
from models.jobs import Job


async def enqueue_resource_metadata_sync(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    resource_id: UUID,
    kind: str,
    initiated_by_user_id: UUID | None = None,
) -> Job:
    """Enqueue one deduplicated provider-owned resource metadata sync."""
    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=kind,
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_resource",
        subject_id=resource_id,
        content_hash=f"{kind}:resource",
        initiated_by_user_id=initiated_by_user_id,
    )
