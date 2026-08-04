# apps/api/services/storage/enqueue_worksapce_bucket_provisioning.py

"""Enqueue private storage provisioning for a newly created workspace."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.storage.domain import PROVISION_WORKSPACE_BUCKET_KIND


async def enqueue_workspace_bucket_provisioning(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    initiated_by_user_id: UUID,
) -> Job:
    """Enqueue one idempotent workspace-owned bucket provisioning job."""
    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=PROVISION_WORKSPACE_BUCKET_KIND,
        workspace_id=workspace_id,
        subject_type="workspace",
        subject_id=workspace_id,
        payload={"workspace_id": str(workspace_id)},
        initiated_by_user_id=initiated_by_user_id,
    )
