# apps/api/services/jobs/handlers/cleanup_platform_artifact_object.py

"""Removes one reserved Artifact object only when its revision never committed."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_MAINTENANCE_KEY
from models.artifacts import Artifact, ArtifactRevision
from models.jobs import Job
from services.artifacts.domain import ARTIFACT_EXTENSIONS, CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND
from services.jobs.registry import job_handler
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider


@job_handler(kind=CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND, timeout=300.0)
async def cleanup_platform_artifact_object(db: AsyncSession, job: Job) -> None:
    """Waits for the parent transaction before checking durable revision ownership."""
    if (
        not db.info.get(SESSION_MAINTENANCE_KEY)
        or job.workspace_id is not None
        or job.concurrency_user_id is not None
        or job.subject_type != "artifact"
        or job.subject_id is None
    ):
        raise RuntimeError("Artifact cleanup requires an unowned maintenance job")
    revision_id = UUID(str(job.payload["revision_id"]))
    extension = str(job.payload["extension"])
    if extension not in ARTIFACT_EXTENSIONS.values():
        raise ValueError("Invalid Artifact revision extension")
    await db.scalar(
        select(Artifact.id)
        .where(
            Artifact.id == job.subject_id,
            Artifact.scope == "platform",
            Artifact.workspace_id.is_(None),
        )
        .with_for_update()
    )
    revision = await db.scalar(
        select(ArtifactRevision.id).where(
            ArtifactRevision.id == revision_id,
            ArtifactRevision.artifact_id == job.subject_id,
            ArtifactRevision.scope == "platform",
            ArtifactRevision.workspace_id.is_(None),
        )
    )
    if revision is None:
        await get_storage_provider().delete_object(
            make_storage_object_ref(
                StorageBucket.PLATFORM_PRIVATE,
                f"platform/artifacts/{job.subject_id}/{revision_id}{extension}",
            )
        )
