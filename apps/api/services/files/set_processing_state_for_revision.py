# apps/api/services/files/set_processing_state_for_revision.py

"""Queues the background processing a new current revision needs."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File, FileRevision
from services.files.contract import is_ingestible
from services.files.queue_video_probe import queue_video_probe
from services.jobs.enqueue_job import enqueue_job
from utils.content import ContentScope


async def set_processing_state_for_revision(
    db: AsyncSession,
    *,
    file: File,
    revision: FileRevision,
    initiated_by_user_id: UUID | None,
    publish_when_ready: bool = False,
) -> None:
    """Set file processing state and enqueue extraction or a video probe for the revision."""
    file.processing_error = None
    file.processing_attempts = 0
    if await queue_video_probe(
        db, file=file, revision=revision, initiated_by_user_id=initiated_by_user_id
    ):
        return
    if not is_ingestible(revision.content_type):
        file.processing_status = "ready"
        return

    file.processing_status = "pending"
    await enqueue_job(
        db,
        kind="files.extract_platform" if file.scope == ContentScope.PLATFORM else "files.extract",
        workspace_id=file.workspace_id,
        concurrency_user_id=initiated_by_user_id if file.scope == ContentScope.PLATFORM else None,
        subject_type="file_revision",
        subject_id=revision.id,
        payload={
            "file_id": str(file.id),
            "revision_id": str(revision.id),
            **({"publish_when_ready": True} if publish_when_ready else {}),
        },
        content_hash=revision.content_hash,
        initiated_by_user_id=initiated_by_user_id,
    )
