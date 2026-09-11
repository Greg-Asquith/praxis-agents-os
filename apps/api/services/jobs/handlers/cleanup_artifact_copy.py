# apps/api/services/jobs/handlers/cleanup_artifact_copy.py

"""Removes reserved workspace copy bytes when their revision never committed."""

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_WORKSPACE_ID_KEY
from models.artifacts import ArtifactRevision
from models.jobs import Job
from services.artifacts.domain import ARTIFACT_EXTENSIONS, CLEANUP_ARTIFACT_COPY_KIND
from services.artifacts.utils import artifact_revision_object_key
from services.jobs.registry import job_handler
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.utils import copy_staging_ref


@job_handler(kind=CLEANUP_ARTIFACT_COPY_KIND, timeout=300.0)
async def cleanup_artifact_copy(db: AsyncSession, job: Job) -> None:
    """The worker claims the reservation only after the copy releases its lock."""
    if (
        job.kind != CLEANUP_ARTIFACT_COPY_KIND
        or job.workspace_id is None
        or db.info.get(SESSION_WORKSPACE_ID_KEY) != job.workspace_id
        or job.concurrency_user_id is not None
        or job.subject_type != "artifact"
        or job.subject_id is None
    ):
        raise RuntimeError("Artifact copy cleanup requires its workspace context")
    revision_id = UUID(str(job.payload["revision_id"]))
    extension = str(job.payload["extension"])
    if (
        revision_id != uuid5(job.subject_id, "revision")
        or extension not in ARTIFACT_EXTENSIONS.values()
    ):
        raise ValueError("Invalid Artifact copy reservation")
    destination = make_storage_object_ref(
        StorageBucket.PRIVATE,
        artifact_revision_object_key(job.workspace_id, job.subject_id, revision_id, extension),
    )
    revision = await db.scalar(
        select(ArtifactRevision.id).where(
            ArtifactRevision.id == revision_id,
            ArtifactRevision.artifact_id == job.subject_id,
            ArtifactRevision.scope == "workspace",
            ArtifactRevision.workspace_id == job.workspace_id,
            ArtifactRevision.object_key == destination.key,
        )
    )
    provider = get_storage_provider()
    if revision is None:
        await provider.delete_object(destination)
    await provider.delete_object(copy_staging_ref(destination))
