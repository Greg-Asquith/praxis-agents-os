# apps/api/services/integrations/enqueue_metadata_sync.py

"""Enqueue provider-declared metadata synchronization."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection
from models.jobs import Job
from services.integrations.plugin import PROVIDER_PLUGINS


async def enqueue_metadata_sync(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    initiated_by_user_id: UUID | None = None,
) -> Job | None:
    """Enqueue one deduplicated metadata sync when the provider contributes one."""
    from services.jobs.enqueue_job import enqueue_job

    plugin = PROVIDER_PLUGINS.get(connection.provider_key)
    kind = plugin.metadata_sync_job_kind if plugin is not None else None
    if kind is None:
        return None
    return await enqueue_job(
        db,
        kind=kind,
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        content_hash=f"{kind}:connection",
        initiated_by_user_id=initiated_by_user_id,
    )
