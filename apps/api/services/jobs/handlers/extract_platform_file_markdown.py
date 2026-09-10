# apps/api/services/jobs/handlers/extract_platform_file_markdown.py

"""Extracts platform drafts through an explicit maintenance transaction."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.dependencies import require_super_admin_user
from core.exceptions.auth import AuthorizationError
from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from models.user import User
from services.files.utils import parse_extraction_payload_ids
from services.jobs.registry import job_handler
from services.jobs.utils import sanitize_error_message
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from utils.digests import sha256_hex
from utils.document_markdown import convert_document_to_markdown

logger = logging.getLogger(__name__)
EXTRACT_PLATFORM_FILE_MARKDOWN_KIND = "files.extract_platform"


@job_handler(kind=EXTRACT_PLATFORM_FILE_MARKDOWN_KIND, timeout=300.0, max_attempts=3)
async def extract_platform_file_markdown(db: AsyncSession, job: Job) -> None:
    """Persists markdown only while the exact platform draft remains unchanged."""
    file_id, revision_id = _validate_job(job)
    await _require_actor(db, job)
    async with maintenance_async_db_session() as db:
        subject = await _load_subject(db, job, file_id, revision_id)
        if subject is None:
            return
        file, revision = subject
        if revision.markdown_object_key:
            return
        version = (file.updated_at, file.is_published, file.published_revision_id)
        filename, content_type = file.name, revision.content_type
        object_key, size_bytes = revision.object_key, revision.size_bytes

    provider = get_storage_provider()
    try:
        source = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, object_key)
        if size_bytes > settings.MAX_FILE_SIZE_DOCUMENT:
            raise ValueError("Platform file exceeds the document size limit")
        data = bytearray()
        async for chunk in provider.stream_object(source):
            if len(data) + len(chunk) > size_bytes:
                raise ValueError("Platform file size differs from its revision")
            data.extend(chunk)
        if len(data) != size_bytes or sha256_hex(bytes(data)) != job.content_hash:
            raise ValueError("Platform file content differs from its revision")
        markdown = await convert_document_to_markdown(
            bytes(data),
            content_type=content_type,
            filename=filename,
            max_bytes=settings.FILES_MAX_MARKDOWN_BYTES,
        )
        markdown_bytes = markdown.encode("utf-8")
        if len(markdown_bytes) > settings.FILES_MAX_MARKDOWN_BYTES:
            raise ValueError("Extracted markdown exceeds its size limit")
        await _persist_markdown(job, file_id, revision_id, version, markdown_bytes)
    except Exception as exc:
        async with maintenance_async_db_session() as db:
            subject = await _load_subject(db, job, file_id, revision_id, lock=True)
            if subject is not None and _same_version(subject, version):
                file, revision = subject
                if not revision.markdown_object_key:
                    file.processing_status = "error"
                    file.processing_error = sanitize_error_message(
                        str(exc) or exc.__class__.__name__
                    )
                    file.processing_attempts = (file.processing_attempts or 0) + 1
        raise


def _validate_job(job: Job) -> tuple[UUID, UUID]:
    if not isinstance(job.payload, dict):
        raise TypeError("Platform extraction requires a valid payload")
    file_id, revision_id = parse_extraction_payload_ids(job.payload)
    if (
        job.workspace_id is not None
        or job.concurrency_user_id is None
        or job.concurrency_user_id != job.initiated_by_user_id
        or job.subject_type != "file_revision"
        or revision_id is None
        or file_id is None
        or job.subject_id != revision_id
        or not job.content_hash
    ):
        raise ValueError("Platform extraction requires an actor-owned revision job")
    return file_id, revision_id


async def _require_actor(db: AsyncSession, job: Job) -> None:
    actor = await db.get(User, job.initiated_by_user_id, populate_existing=True)
    if actor is None or actor.deleted or not actor.is_active:
        raise AuthorizationError("Platform extraction requires an active super admin")
    require_super_admin_user(actor)


async def _load_subject(
    db: AsyncSession, job: Job, file_id: UUID, revision_id: UUID, *, lock: bool = False
) -> tuple[File, FileRevision] | None:
    await _require_actor(db, job)
    statement = select(File).where(
        File.id == file_id,
        File.scope == "platform",
        File.workspace_id.is_(None),
        File.deleted.is_(False),
        File.current_revision_id == revision_id,
    )
    if lock:
        statement = statement.with_for_update()
    file = await db.scalar(statement)
    if file is None or (not file.is_published and file.published_revision_id is not None):
        return None
    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id,
            FileRevision.file_id == file_id,
            FileRevision.scope == "platform",
            FileRevision.workspace_id.is_(None),
            FileRevision.content_hash == job.content_hash,
        )
    )
    return (file, revision) if revision is not None else None


def _same_version(subject: tuple[File, FileRevision], version: tuple) -> bool:
    file, _revision = subject
    return (file.updated_at, file.is_published, file.published_revision_id) == version


async def _persist_markdown(
    job: Job, file_id: UUID, revision_id: UUID, version: tuple, markdown: bytes
) -> None:
    provider = get_storage_provider()
    destination = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE,
        f"platform/files/{file_id}/{revision_id}.extracted.md",
    )
    async with maintenance_async_db_session() as db:
        subject = await _load_subject(db, job, file_id, revision_id, lock=True)
        if subject is None or not _same_version(subject, version):
            return
        file, revision = subject
        if revision.markdown_object_key:
            return
        attempted_write = False
        try:
            existing = await provider.stat_object(destination)
            if existing is None:
                attempted_write = True
                await provider.put_object(
                    destination, markdown, content_type="text/markdown", overwrite=False
                )
            else:
                offset = 0
                async for chunk in provider.stream_object(destination):
                    if chunk != markdown[offset : offset + len(chunk)]:
                        raise ValueError("Existing extracted markdown differs from this revision")
                    offset += len(chunk)
                if offset != len(markdown):
                    raise ValueError("Existing extracted markdown differs from this revision")
        except BaseException:
            # Retain the parent lock until cleanup finishes so a retry cannot adopt deleted output.
            if attempted_write:
                try:
                    await provider.delete_object(destination)
                except Exception:
                    logger.warning("Failed to remove platform extraction output", exc_info=True)
            raise
        revision.markdown_object_key = destination.key
        revision.markdown_size_bytes = len(markdown)
        file.processing_status = "ready"
        file.processing_error = None
        file.processing_attempts = (file.processing_attempts or 0) + 1
        await db.flush()
