# apps/api/services/jobs/handlers/probe_video.py

"""Measures workspace video revisions on the media renderer."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from services.files.domain import VIDEO_PROBE_JOB_KIND, VideoMetadata
from services.files.utils import format_duration, parse_extraction_payload_ids
from services.jobs.registry import job_handler
from services.media.domain import MediaRendererError, ProbeOperation
from services.media.run_media_operation import REQUEST_ALLOWANCE_SECONDS, run_media_operation

logger = logging.getLogger(__name__)

# Retrying these can't change the answer, so the File fails without another download.
PERMANENT_FAILURES: dict[str, str | None] = {
    "invalid_media": "The video couldn't be read. Check that it plays, then upload it again.",
    "no_video": "The file has no video.",
    "resource_limit": "The video is too large or complex to prepare.",
    "input_too_large": "The video is too large to prepare.",
    "forbidden": None,
    "unsupported": None,
}


class VideoRejectedError(Exception):
    """A probe result the File can't keep, with a reason safe to show."""


@job_handler(
    kind=VIDEO_PROBE_JOB_KIND,
    timeout=settings.MEDIA_RENDERER_TIMEOUT_SECONDS + REQUEST_ALLOWANCE_SECONDS + 60,
    max_attempts=3,
)
async def probe_video(db: AsyncSession, job: Job) -> None:
    """Stores one video revision's probe result, or fails its File with a plain reason."""
    if job.workspace_id is None:
        return
    file_id, revision_id = parse_extraction_payload_ids(job.payload)
    if file_id is None or revision_id is None:
        logger.warning("Skipping video probe with invalid payload", extra={"job_id": str(job.id)})
        return
    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id,
            FileRevision.file_id == file_id,
            FileRevision.scope == "workspace",
            FileRevision.workspace_id == job.workspace_id,
        )
    )
    file = await db.scalar(
        select(File).where(
            File.id == file_id,
            File.scope == "workspace",
            File.workspace_id == job.workspace_id,
        )
    )
    if revision is None or file is None or file.deleted:
        logger.info("Skipping video probe for a missing file", extra={"job_id": str(job.id)})
        return

    is_current = file.current_revision_id == revision.id
    if revision.media_metadata is None:
        metadata = await _restored_metadata(db, revision)
        if metadata is None:
            metadata = await _measure(db, file, revision, is_current=is_current)
        if metadata is None:
            return
        revision.media_metadata = metadata
    if is_current:
        file.processing_status = "ready"
        file.processing_error = None
    await db.flush()


async def _measure(
    db: AsyncSession, file: File, revision: FileRevision, *, is_current: bool
) -> dict[str, object] | None:
    """Returns the probe result, None after a permanent failure, or raises to retry."""
    if is_current:
        file.processing_status = "processing"
        file.processing_attempts = (file.processing_attempts or 0) + 1
        file.processing_error = None
        await db.commit()
    try:
        return await _probe(revision)
    except (MediaRendererError, VideoRejectedError) as exc:
        await _fail(db, file, is_current=is_current, exc=exc)
        if isinstance(exc, MediaRendererError) and exc.code not in PERMANENT_FAILURES:
            raise
        return None


async def _probe(revision: FileRevision) -> dict[str, object]:
    operation = await run_media_operation(
        workspace_id=revision.workspace_id, source=revision, operation=ProbeOperation()
    )
    result = operation.result
    if not isinstance(result, VideoMetadata):
        raise MediaRendererError("invalid_response", "The media renderer gave an invalid answer.")
    if result.video_codec is None or result.duration_ms <= 0:
        raise VideoRejectedError(PERMANENT_FAILURES["no_video"])
    limit_ms = settings.VIDEO_MAX_SOURCE_DURATION_SECONDS * 1000
    if result.duration_ms > limit_ms:
        raise VideoRejectedError(
            f"The video is {format_duration(result.duration_ms)} long. "
            f"Videos can be up to {format_duration(limit_ms)}."
        )
    return result.model_dump(mode="json")


async def _restored_metadata(db: AsyncSession, revision: FileRevision) -> dict | None:
    if revision.revision_kind != "restore" or revision.restored_from_revision_id is None:
        return None
    return await db.scalar(
        select(FileRevision.media_metadata).where(
            FileRevision.id == revision.restored_from_revision_id,
            FileRevision.file_id == revision.file_id,
            FileRevision.workspace_id == revision.workspace_id,
        )
    )


async def _fail(
    db: AsyncSession, file: File, *, is_current: bool, exc: MediaRendererError | VideoRejectedError
) -> None:
    if not is_current:
        return
    if isinstance(exc, MediaRendererError):
        message = PERMANENT_FAILURES.get(exc.code) or exc.message
    else:
        message = str(exc)
    file.processing_status = "error"
    file.processing_error = message
    await db.commit()
