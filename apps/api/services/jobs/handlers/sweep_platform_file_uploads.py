"""Removes expired platform staging objects and interrupted promotions."""

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import FileRevision, FileUpload
from models.jobs import Job
from services.jobs.enqueue_job import enqueue_job
from services.jobs.handlers.sweep_platform_files import require_platform_maintenance_job
from services.jobs.registry import job_handler
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider

SWEEP_PLATFORM_FILE_UPLOADS_KIND = "platform.files.sweep_uploads"
_SWEEP_BATCH_SIZE = 100


@job_handler(kind=SWEEP_PLATFORM_FILE_UPLOADS_KIND, timeout=300.0)
async def sweep_platform_file_uploads(db: AsyncSession, job: Job) -> None:
    """Cleans one grant batch, retaining evidence when provider deletion fails."""
    require_platform_maintenance_job(db, job)
    now = datetime.now(UTC)
    uploads = (
        await db.scalars(
            select(FileUpload)
            .where(
                FileUpload.scope == "platform",
                FileUpload.workspace_id.is_(None),
                FileUpload.expires_at < now,
            )
            .order_by(FileUpload.expires_at, FileUpload.id)
            .limit(_SWEEP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    ).all()
    provider = get_storage_provider()
    for upload in uploads:
        extension = PurePosixPath(upload.filename).suffix.lower()
        durable_key = f"platform/files/{upload.file_id}/{upload.revision_id}{extension}"
        for key in (upload.object_key, durable_key):
            referenced = await db.scalar(
                select(FileRevision.id)
                .where(
                    FileRevision.scope == "platform",
                    or_(FileRevision.object_key == key, FileRevision.markdown_object_key == key),
                )
                .limit(1)
            )
            if referenced is None:
                await provider.delete_object(
                    make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, key)
                )
        await db.delete(upload)
    await enqueue_job(
        db,
        kind=SWEEP_PLATFORM_FILE_UPLOADS_KIND,
        content_hash=f"platform-file-uploads:{job.id}",
        run_after=now + timedelta(seconds=settings.FILES_SWEEP_INTERVAL_SECONDS),
    )
