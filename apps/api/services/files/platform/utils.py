# apps/api/services/files/platform/utils.py

"""Authority, ownership, and storage checks for platform File management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.dependencies import require_super_admin_user
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.files import File, FileRevision
from models.user import User
from services.audit_events import AuditResourceType
from services.audit_events.platform_content_events import (
    PlatformContentAuditDetails,
    record_platform_content_audit_event,
)
from services.files.contract import max_size_bytes, require_matching_pair
from services.files.domain import FileRead
from services.files.utils import file_to_read
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import StoragePreconditionError
from services.storage.factory import get_storage_provider
from services.storage.utils import read_copy_content
from utils.content import ContentScope


@asynccontextmanager
async def platform_session(db: AsyncSession, actor: User) -> AsyncIterator[AsyncSession]:
    """Checks authority before releasing tenant locks and opening maintenance access."""
    require_super_admin_user(actor)
    await db.commit()
    async with maintenance_async_db_session() as maintenance_db:
        yield maintenance_db


async def get_platform_file(db: AsyncSession, *, file_id: UUID, for_update: bool = False) -> File:
    statement = select(File).where(
        File.id == file_id,
        File.scope == ContentScope.PLATFORM,
        File.workspace_id.is_(None),
        File.deleted.is_(False),
    )
    if for_update:
        statement = statement.with_for_update()
    file = await db.scalar(statement)
    if file is None:
        raise NotFoundError("File not found", resource_type="file", resource_id=str(file_id))
    return file


async def get_platform_revision(
    db: AsyncSession, *, file: File, revision_id: UUID | None
) -> FileRevision:
    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id,
            FileRevision.file_id == file.id,
            FileRevision.scope == ContentScope.PLATFORM,
            FileRevision.workspace_id.is_(None),
        )
    )
    if revision is None:
        raise NotFoundError(
            "File revision not found", resource_type="file_revision", resource_id=str(revision_id)
        )
    return revision


def platform_file_to_read(file: File, actor: User) -> FileRead:
    return file_to_read(file, folder_name=None, actor=actor)


async def record_file_change(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    file: File,
    details: PlatformContentAuditDetails,
) -> None:
    await db.flush()
    await record_platform_content_audit_event(
        db,
        request=request,
        actor=actor,
        resource_type=AuditResourceType.FILE,
        resource_id=file.id,
        details=details,
    )
    await db.refresh(file)


async def read_revision_bytes(revision: FileRevision) -> bytes:
    """Reads only bounded bytes matching the confirmed revision."""
    entry = require_matching_pair(revision.content_type, revision.extension)
    if not 0 < revision.size_bytes <= max_size_bytes(entry):
        raise AppValidationError("File revision exceeds the content limit", field="revision_id")
    return await read_copy_content(
        get_storage_provider(),
        make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
        revision.size_bytes,
        revision.content_hash,
    )


async def read_revision_markdown(revision: FileRevision) -> bytes:
    """Reads stored extraction within its recorded size and configured limit."""
    expected_size = revision.markdown_size_bytes
    if not revision.markdown_object_key or expected_size is None:
        raise AppValidationError("The file preview is not ready", field="revision_id")
    if not 0 <= expected_size <= settings.FILES_MAX_MARKDOWN_BYTES:
        raise AppValidationError("File preview exceeds the content limit", field="revision_id")
    ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.markdown_object_key)
    content = bytearray()
    async for chunk in get_storage_provider().stream_object(ref):
        if len(content) + len(chunk) > expected_size:
            raise StoragePreconditionError("File preview size changed", operation="file_preview")
        content.extend(chunk)
    if len(content) != expected_size:
        raise StoragePreconditionError("File preview size changed", operation="file_preview")
    return bytes(content)


async def publish_locked_revision(
    db: AsyncSession,
    *,
    file: File,
    revision: FileRevision,
    actor: User,
    request: Request | None,
) -> None:
    """Publishes verified content and audit evidence while the caller holds its parent lock."""
    actor = await db.get(User, actor.id, populate_existing=True)
    if actor is None or actor.deleted or not actor.is_active:
        raise AuthorizationError("Platform publication requires an active super admin")
    require_super_admin_user(actor)
    if file.current_revision_id != revision.id:
        raise ConflictError("File has changed", conflicting_resource="file")
    if file.processing_status != "ready":
        raise AppValidationError("File processing must finish before publication")
    await read_revision_bytes(revision)
    if file.is_published and file.published_revision_id == revision.id:
        return
    previous = file.published_revision_id
    revision.is_published = True
    await db.flush()
    file.published_revision_id = revision.id
    file.is_published = True
    await record_file_change(
        db,
        request=request,
        actor=actor,
        file=file,
        details=PlatformContentAuditDetails(
            operation="publish",
            revision_id=revision.id,
            previous_revision_id=previous,
        ),
    )
