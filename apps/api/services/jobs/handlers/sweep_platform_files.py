"""Bounded retention for deployment-owned File revisions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_MAINTENANCE_KEY
from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from models.kb import KBDocument
from services.files.utils import distinct_object_keys
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.enqueue_job import enqueue_job
from services.jobs.registry import job_handler
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider

SWEEP_PLATFORM_FILES_KIND = "platform.files.sweep_deleted"
_SWEEP_BATCH_SIZE = 100


@job_handler(kind=SWEEP_PLATFORM_FILES_KIND, timeout=300.0)
async def sweep_platform_files(db: AsyncSession, job: Job) -> None:
    """Deletes at most one revision batch, preserving live knowledge pins."""
    require_platform_maintenance_job(db, job)
    now = datetime.now(UTC)
    pinned = (
        select(KBDocument.id)
        .join(FileRevision, FileRevision.id == KBDocument.file_revision_id)
        .where(
            FileRevision.file_id == File.id,
            KBDocument.scope == "platform",
            KBDocument.deleted.is_(False),
        )
        .exists()
    )
    files = (
        await db.scalars(
            select(File)
            .where(
                File.scope == "platform",
                File.workspace_id.is_(None),
                File.deleted.is_(True),
                File.deleted_at < now - timedelta(days=settings.FILES_DELETED_RETENTION_DAYS),
                ~pinned,
            )
            .order_by(File.deleted_at, File.id)
            .limit(_SWEEP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    ).all()
    remaining = _SWEEP_BATCH_SIZE
    provider = get_storage_provider()
    for file in files:
        revisions = list(
            (
                await db.scalars(
                    select(FileRevision)
                    .where(FileRevision.file_id == file.id, FileRevision.scope == "platform")
                    .order_by(FileRevision.revision_number.desc())
                    .limit(remaining)
                    .with_for_update()
                )
            ).all()
        )
        remaining -= len(revisions)
        # A pin can commit while revision locks are acquired.
        if await db.scalar(select(File.id).where(File.id == file.id, pinned)):
            if remaining == 0:
                break
            continue
        # Clear pointers before removing their targets across successive bounded passes.
        file.is_published = False
        file.published_revision_id = None
        file.current_revision_id = None
        await db.flush()
        keys = distinct_object_keys(revisions)
        keys.update(
            f"platform/files/{file.id}/{revision.id}.extracted.md" for revision in revisions
        )
        for key in keys:
            await provider.delete_object(
                make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, key)
            )
        for revision in revisions:
            await db.delete(revision)
            await db.flush()
        if not await db.scalar(
            select(FileRevision.id).where(FileRevision.file_id == file.id).limit(1)
        ):
            await db.delete(file)
        if remaining == 0:
            break
    await enqueue_job(
        db,
        kind=SWEEP_PLATFORM_FILES_KIND,
        content_hash=f"platform-files:{job.id}",
        run_after=now + timedelta(seconds=settings.FILES_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_platform_files_sweep_jobs(db: AsyncSession) -> None:
    """Ensures both platform retention jobs have an in-flight pass."""
    from services.jobs.handlers.sweep_platform_file_uploads import SWEEP_PLATFORM_FILE_UPLOADS_KIND

    if not db.info.get(SESSION_MAINTENANCE_KEY):
        raise RuntimeError("Platform retention requires a maintenance session")
    for kind in (SWEEP_PLATFORM_FILES_KIND, SWEEP_PLATFORM_FILE_UPLOADS_KIND):
        existing = await db.scalar(
            select(Job.id).where(Job.kind == kind, Job.status.in_(IN_FLIGHT_JOB_STATUSES)).limit(1)
        )
        if existing is None:
            await enqueue_job(db, kind=kind, content_hash=f"{kind}:ensure")


def require_platform_maintenance_job(db: AsyncSession, job: Job) -> None:
    """Rejects tenant-owned jobs before accessing platform storage."""
    if (
        not db.info.get(SESSION_MAINTENANCE_KEY)
        or job.workspace_id is not None
        or job.concurrency_user_id is not None
    ):
        raise RuntimeError("Platform retention requires an unowned maintenance job")
