# apps/api/services/files/queue_video_probe.py

"""Queues the renderer probe for a new workspace video revision."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import File, FileRevision
from services.files.contract import FileCategory, contract_for_content_type
from services.files.domain import VIDEO_PROBE_JOB_KIND
from services.jobs.enqueue_job import enqueue_job


async def queue_video_probe(
    db: AsyncSession,
    *,
    file: File,
    revision: FileRevision,
    initiated_by_user_id: UUID | None,
) -> bool:
    """Marks a workspace video pending and queues its probe.

    Returns false, changing nothing, for other files or when the renderer is
    unavailable; those videos stay ready without measured metadata.
    """
    if (
        revision.scope != "workspace"
        or contract_for_content_type(revision.content_type).category != FileCategory.VIDEO
        or not settings.media_renderer_available
    ):
        return False
    file.processing_status = "pending"
    file.processing_error = None
    file.processing_attempts = 0
    await enqueue_job(
        db,
        kind=VIDEO_PROBE_JOB_KIND,
        workspace_id=revision.workspace_id,
        subject_type="file_revision",
        subject_id=revision.id,
        payload={"file_id": str(file.id), "revision_id": str(revision.id)},
        content_hash=revision.content_hash,
        initiated_by_user_id=initiated_by_user_id,
    )
    return True
