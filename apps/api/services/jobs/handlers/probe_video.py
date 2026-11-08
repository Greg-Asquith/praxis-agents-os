# apps/api/services/jobs/handlers/probe_video.py

"""Measures workspace video and audio revisions on the media renderer."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from services.files.contract import FileCategory, contract_for_content_type
from services.files.domain import VIDEO_PROBE_JOB_KIND, VideoMetadata
from services.files.fail_file_processing import fail_file_processing
from services.files.utils import (
    format_duration,
    lock_current_revision_file,
    parse_extraction_payload_ids,
)
from services.jobs.registry import job_handler
from services.media.domain import INVALID_RESPONSE_MESSAGE, MediaRendererError, ProbeOperation
from services.media.run_media_operation import REQUEST_ALLOWANCE_SECONDS, run_media_operation

logger = logging.getLogger(__name__)

# Lets the job outlast the renderer request it waits on.
JOB_ALLOWANCE_SECONDS = 60

# Retrying these can't change the answer, so the File fails without another download.
PERMANENT_FAILURES: dict[str, str | None] = {
    "invalid_media": "The video couldn't be read. Check that it plays, then upload it again.",
    "no_video": "The file has no video.",
    "no_audio": "The file has no sound.",
    "resource_limit": "The video is too large or complex to prepare.",
    "input_too_large": "The video is too large to prepare.",
    "forbidden": None,
    "unsupported": None,
}


class VideoRejectedError(Exception):
    """A probe result the File can't keep, with a reason safe to show."""


@job_handler(
    kind=VIDEO_PROBE_JOB_KIND,
    timeout=settings.MEDIA_RENDERER_TIMEOUT_SECONDS
    + REQUEST_ALLOWANCE_SECONDS
    + JOB_ALLOWANCE_SECONDS,
    max_attempts=3,
    on_final_failure=fail_file_processing,
)
async def probe_video(db: AsyncSession, job: Job) -> None:
    """Stores one video or audio revision's probe result, or fails its File with a plain reason."""
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

    if revision.media_metadata is None:
        metadata = await _restored_metadata(db, revision)
        if metadata is None:
            metadata = await _measure(db, file, revision)
        if metadata is None:
            return
        revision.media_metadata = metadata
    if await _lock_current(db, file, revision) is not None:
        file.processing_status = "ready"
        file.processing_error = None
    await db.flush()


async def _measure(db: AsyncSession, file: File, revision: FileRevision) -> dict | None:
    """Returns the probe result, None after a permanent failure, or raises to retry."""
    if await _lock_current(db, file, revision) is not None:
        file.processing_status = "processing"
        file.processing_attempts = (file.processing_attempts or 0) + 1
        file.processing_error = None
    await db.commit()
    try:
        return await _probe(revision)
    except VideoRejectedError as exc:
        await _fail(db, file, revision, str(exc))
    except MediaRendererError as exc:
        if exc.code not in PERMANENT_FAILURES:
            raise
        await _fail(db, file, revision, PERMANENT_FAILURES[exc.code] or exc.message)
    return None


async def _lock_current(db: AsyncSession, file: File, revision: FileRevision) -> File | None:
    return await lock_current_revision_file(
        db, file_id=file.id, revision_id=revision.id, workspace_id=revision.workspace_id
    )


async def _probe(revision: FileRevision) -> dict[str, object]:
    operation = await run_media_operation(
        workspace_id=revision.workspace_id, sources=[revision], operation=ProbeOperation()
    )
    result = operation.result
    if not isinstance(result, VideoMetadata):
        raise MediaRendererError("invalid_response", INVALID_RESPONSE_MESSAGE)
    audio = contract_for_content_type(revision.content_type).category == FileCategory.AUDIO
    if audio and (not result.has_audio or result.duration_ms <= 0):
        raise VideoRejectedError(PERMANENT_FAILURES["no_audio"])
    if not audio and (result.video_codec is None or result.duration_ms <= 0):
        raise VideoRejectedError(PERMANENT_FAILURES["no_video"])
    limit_ms = settings.VIDEO_MAX_SOURCE_DURATION_SECONDS * 1000
    if result.duration_ms > limit_ms:
        kind, kinds = ("audio", "Audio files") if audio else ("video", "Videos")
        raise VideoRejectedError(
            f"The {kind} is {format_duration(result.duration_ms)} long. "
            f"{kinds} can be up to {format_duration(limit_ms)}."
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


async def _fail(db: AsyncSession, file: File, revision: FileRevision, message: str) -> None:
    if await _lock_current(db, file, revision) is None:
        return
    file.processing_status = "error"
    file.processing_error = message
    await db.commit()
