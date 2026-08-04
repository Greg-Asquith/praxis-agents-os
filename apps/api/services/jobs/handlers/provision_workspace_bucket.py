# apps/api/services/jobs/handlers/provision_workspace_bucket.py

"""Provision workspace-private object storage."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.registry import job_handler
from services.storage.domain import PROVISION_WORKSPACE_BUCKET_KIND
from services.storage.factory import get_storage_provider


@job_handler(kind=PROVISION_WORKSPACE_BUCKET_KIND, timeout=120.0, max_attempts=5)
async def provision_workspace_bucket(_db: AsyncSession, job: Job) -> None:
    """Create and harden the private bucket for the job's workspace."""
    if job.workspace_id is None:
        raise RuntimeError("Workspace bucket provisioning requires a workspace-owned job")
    await get_storage_provider().ensure_workspace_bucket(job.workspace_id)
