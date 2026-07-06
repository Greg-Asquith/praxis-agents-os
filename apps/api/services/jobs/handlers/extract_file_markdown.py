# apps/api/services/jobs/handlers/extract_file_markdown.py

"""Extract workspace file revisions to markdown."""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from services.files.utils import private_ref_from_key, revision_markdown_key
from services.jobs.registry import job_handler
from services.jobs.utils import sanitize_error_message
from services.storage.factory import get_storage_provider
from utils.document_markdown import convert_document_to_markdown

logger = logging.getLogger(__name__)

EXTRACT_FILE_MARKDOWN_KIND = "files.extract"


@job_handler(kind=EXTRACT_FILE_MARKDOWN_KIND, timeout=300.0, max_attempts=3)
async def extract_file_markdown(db: AsyncSession, job: Job) -> None:
    """Extract one file revision to markdown and backfill the revision."""
    file_id, revision_id = _parse_payload_ids(job.payload)
    if file_id is None or revision_id is None:
        logger.warning(
            "Skipping file extraction job with invalid payload",
            extra={"job_id": str(job.id), "payload": job.payload},
        )
        return

    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id,
            FileRevision.workspace_id == job.workspace_id,
        )
    )
    if revision is None:
        logger.info(
            "Skipping file extraction for missing revision",
            extra={"job_id": str(job.id), "revision_id": str(revision_id)},
        )
        return

    file = await db.scalar(
        select(File).where(
            File.id == file_id,
            File.workspace_id == revision.workspace_id,
        )
    )
    if file is None or file.deleted:
        logger.info(
            "Skipping file extraction for missing or deleted file",
            extra={"job_id": str(job.id), "file_id": str(file_id)},
        )
        return

    if revision.markdown_object_key:
        _mark_current_revision_ready(file, revision)
        return

    if await _copy_restored_markdown(db, file=file, revision=revision):
        return

    is_current_revision = file.current_revision_id == revision.id
    if is_current_revision:
        file.processing_status = "processing"
        file.processing_attempts = (file.processing_attempts or 0) + 1
        file.processing_error = None
        await db.commit()

    provider = get_storage_provider()
    try:
        data = await provider.get_object(private_ref_from_key(revision.object_key))
        markdown = await convert_document_to_markdown(
            data,
            content_type=revision.content_type,
            filename=file.name,
            max_bytes=settings.FILES_MAX_MARKDOWN_BYTES,
        )
        markdown_ref = private_ref_from_key(
            revision_markdown_key(revision.workspace_id, revision.file_id, revision.id)
        )
        markdown_bytes = markdown.encode("utf-8")
        await provider.put_object(markdown_ref, markdown_bytes, content_type="text/markdown")
        revision.markdown_object_key = markdown_ref.key
        revision.markdown_size_bytes = len(markdown_bytes)
        if is_current_revision:
            file.processing_status = "ready"
            file.processing_error = None
        await db.flush()
    except Exception as exc:
        if is_current_revision:
            file.processing_status = "error"
            file.processing_error = sanitize_error_message(str(exc) or exc.__class__.__name__)
            await db.commit()
        raise


async def _copy_restored_markdown(
    db: AsyncSession,
    *,
    file: File,
    revision: FileRevision,
) -> bool:
    if revision.revision_kind != "restore" or revision.restored_from_revision_id is None:
        return False

    source = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision.restored_from_revision_id,
            FileRevision.workspace_id == revision.workspace_id,
        )
    )
    if source is None or not source.markdown_object_key:
        return False

    revision.markdown_object_key = source.markdown_object_key
    revision.markdown_size_bytes = source.markdown_size_bytes
    _mark_current_revision_ready(file, revision)
    await db.flush()
    return True


def _mark_current_revision_ready(file: File, revision: FileRevision) -> None:
    if file.current_revision_id != revision.id:
        return
    if file.processing_status in {"pending", "processing"}:
        file.processing_status = "ready"
        file.processing_error = None


def _parse_payload_ids(payload: dict[str, Any]) -> tuple[UUID | None, UUID | None]:
    try:
        file_id = UUID(str(payload.get("file_id")))
        revision_id = UUID(str(payload.get("revision_id")))
    except (TypeError, ValueError, AttributeError):
        return None, None
    return file_id, revision_id
