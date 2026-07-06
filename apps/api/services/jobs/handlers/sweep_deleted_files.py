# apps/api/services/jobs/handlers/sweep_deleted_files.py

"""Retention sweeper for deleted files and abandoned uploads."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import File, FileRevision, FileUpload
from models.jobs import Job
from services.files.utils import best_effort_delete_file_object, distinct_object_keys
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.registry import job_handler
from services.storage.factory import get_storage_provider

SWEEP_DELETED_FILES_KIND = "files.sweep_deleted"
_SWEEP_BATCH_SIZE = 100


@job_handler(kind=SWEEP_DELETED_FILES_KIND, timeout=300.0)
async def sweep_deleted_files(db: AsyncSession, job: Job) -> None:
    """Hard-delete expired file tombstones and stale upload grants."""
    now = datetime.now(UTC)
    await _purge_expired_deleted_files(db, now=now)
    await _purge_expired_uploads(db, now=now)

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=SWEEP_DELETED_FILES_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-files:{job.id}",
        run_after=now + timedelta(seconds=settings.FILES_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_files_sweep_job(db: AsyncSession) -> Job:
    """Ensure at least one file-retention sweep is pending or running."""
    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_DELETED_FILES_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=SWEEP_DELETED_FILES_KIND,
        content_hash="sweep-files:ensure",
        run_after=datetime.now(UTC),
    )


async def _purge_expired_deleted_files(db: AsyncSession, *, now: datetime) -> None:
    cutoff = now - timedelta(days=settings.FILES_DELETED_RETENTION_DAYS)
    files = (
        await db.scalars(
            select(File)
            .where(
                File.deleted.is_(True),
                File.deleted_at.is_not(None),
                File.deleted_at < cutoff,
            )
            .order_by(File.deleted_at, File.id)
            .limit(_SWEEP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not files:
        return

    provider = get_storage_provider()
    for file in files:
        revisions = (
            await db.scalars(
                select(FileRevision).where(
                    FileRevision.file_id == file.id,
                    FileRevision.workspace_id == file.workspace_id,
                )
            )
        ).all()
        for object_key in distinct_object_keys(list(revisions)):
            await best_effort_delete_file_object(object_key, provider=provider)
        await db.delete(file)


async def _purge_expired_uploads(db: AsyncSession, *, now: datetime) -> None:
    uploads = (
        await db.scalars(
            select(FileUpload)
            .where(
                FileUpload.consumed_at.is_(None),
                FileUpload.expires_at < now,
            )
            .order_by(FileUpload.expires_at, FileUpload.id)
            .limit(_SWEEP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not uploads:
        return

    provider = get_storage_provider()
    for upload in uploads:
        await best_effort_delete_file_object(upload.object_key, provider=provider)
        await db.delete(upload)
