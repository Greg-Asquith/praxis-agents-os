# apps/api/services/jobs/handlers/sweep_platform_artifacts.py

"""Purges expired platform Artifact tombstones in bounded revision batches."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_MAINTENANCE_KEY
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision
from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.enqueue_job import enqueue_job
from services.jobs.handlers.sweep_platform_files import require_platform_maintenance_job
from services.jobs.registry import job_handler
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.utils import copy_staging_ref

SWEEP_PLATFORM_ARTIFACTS_KIND = "platform.artifacts.sweep_deleted"
_SWEEP_BATCH_SIZE = 100


@job_handler(kind=SWEEP_PLATFORM_ARTIFACTS_KIND, timeout=300.0)
async def sweep_platform_artifacts(db: AsyncSession, job: Job) -> None:
    """Removes expired platform revisions while retaining failed deletions for retry."""
    require_platform_maintenance_job(db, job)
    now = datetime.now(UTC)
    artifacts = list(
        await db.scalars(
            select(Artifact)
            .where(
                Artifact.scope == "platform",
                Artifact.workspace_id.is_(None),
                Artifact.deleted.is_(True),
                Artifact.deleted_at < now - timedelta(days=settings.FILES_DELETED_RETENTION_DAYS),
            )
            .order_by(Artifact.deleted_at, Artifact.id)
            .limit(_SWEEP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    )
    remaining = _SWEEP_BATCH_SIZE
    provider = get_storage_provider()
    for artifact in artifacts:
        revisions = list(
            await db.scalars(
                select(ArtifactRevision)
                .where(
                    ArtifactRevision.artifact_id == artifact.id,
                    ArtifactRevision.scope == "platform",
                    ArtifactRevision.workspace_id.is_(None),
                )
                .order_by(ArtifactRevision.revision_number.desc())
                .limit(remaining)
                .with_for_update()
            )
        )
        remaining -= len(revisions)
        artifact.is_published = False
        artifact.published_version_id = None
        artifact.current_version_id = None
        await db.flush()
        # Remove restored versions before the earlier versions they reference.
        for revision in revisions:
            destination = make_storage_object_ref(
                StorageBucket.PLATFORM_PRIVATE, revision.object_key
            )
            await provider.delete_object(destination)
            await provider.delete_object(copy_staging_ref(destination))
            await db.delete(revision)
            await db.flush()
        if not await db.scalar(
            select(ArtifactRevision.id).where(ArtifactRevision.artifact_id == artifact.id).limit(1)
        ):
            await db.delete(artifact)
        if remaining == 0:
            break
    await enqueue_job(
        db,
        kind=SWEEP_PLATFORM_ARTIFACTS_KIND,
        content_hash=f"platform-artifacts:{job.id}",
        run_after=now + timedelta(seconds=settings.FILES_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_platform_artifacts_sweep_job(db: AsyncSession) -> None:
    """Ensures an unowned platform Artifact retention pass is pending or running."""
    if not db.info.get(SESSION_MAINTENANCE_KEY):
        raise RuntimeError("Platform retention requires a maintenance session")
    existing = await db.scalar(
        select(Job.id)
        .where(Job.kind == SWEEP_PLATFORM_ARTIFACTS_KIND, Job.status.in_(IN_FLIGHT_JOB_STATUSES))
        .limit(1)
    )
    if existing is None:
        await enqueue_job(
            db,
            kind=SWEEP_PLATFORM_ARTIFACTS_KIND,
            content_hash=f"{SWEEP_PLATFORM_ARTIFACTS_KIND}:ensure",
        )
