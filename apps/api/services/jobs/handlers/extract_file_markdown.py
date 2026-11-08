# apps/api/services/jobs/handlers/extract_file_markdown.py

"""Extract workspace file revisions to markdown."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from services.files.fail_file_processing import fail_file_processing
from services.files.utils import (
    lock_current_revision_file,
    parse_extraction_payload_ids,
    private_ref_from_key,
    revision_markdown_key,
)
from services.jobs.registry import job_handler
from services.storage.factory import get_storage_provider
from utils.document_markdown import convert_document_to_markdown

logger = logging.getLogger(__name__)

EXTRACT_FILE_MARKDOWN_KIND = "files.extract"


@job_handler(
    kind=EXTRACT_FILE_MARKDOWN_KIND,
    timeout=300.0,
    max_attempts=3,
    on_final_failure=fail_file_processing,
)
async def extract_file_markdown(db: AsyncSession, job: Job) -> None:
    """Extract one file revision to markdown and backfill the revision."""
    if job.workspace_id is None:
        return
    file_id, revision_id = parse_extraction_payload_ids(job.payload)
    if file_id is None or revision_id is None:
        logger.warning(
            "Skipping file extraction job with invalid payload",
            extra={"job_id": str(job.id), "payload": job.payload},
        )
        return

    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id,
            FileRevision.file_id == file_id,
            FileRevision.scope == "workspace",
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
            File.scope == "workspace",
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

    if await _lock_current(db, file, revision) is not None:
        file.processing_status = "processing"
        file.processing_attempts = (file.processing_attempts or 0) + 1
        file.processing_error = None
    await db.commit()

    # Failures raise, so the job retries; fail_file_processing marks the File after the last one.
    provider = get_storage_provider()
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
    if await _lock_current(db, file, revision) is not None:
        file.processing_status = "ready"
        file.processing_error = None
    await db.flush()


async def _lock_current(db: AsyncSession, file: File, revision: FileRevision) -> File | None:
    return await lock_current_revision_file(
        db, file_id=file.id, revision_id=revision.id, workspace_id=revision.workspace_id
    )


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
            FileRevision.file_id == revision.file_id,
            FileRevision.scope == "workspace",
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
