# apps/api/services/files/platform/publish_file.py

"""Publishes a reviewed platform File revision atomically."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.files.domain import FileRead, PlatformFilePublishRequest
from services.files.platform.utils import (
    get_platform_file,
    get_platform_revision,
    platform_file_to_read,
    platform_session,
    read_revision_bytes,
    record_file_change,
)


async def publish_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    file_id: UUID,
    payload: PlatformFilePublishRequest,
) -> FileRead:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id, for_update=True)
        if file.current_revision_id != payload.expected_current_revision_id:
            raise ConflictError("File has changed", conflicting_resource="file")
        revision = await get_platform_revision(
            maintenance_db, file=file, revision_id=file.current_revision_id
        )
        if file.processing_status != "ready":
            raise AppValidationError("File processing must finish before publication")
        await read_revision_bytes(revision)
        if file.is_published and file.published_revision_id == revision.id:
            return platform_file_to_read(file, actor)
        previous = file.published_revision_id
        revision.is_published = True
        await maintenance_db.flush()
        file.published_revision_id = revision.id
        file.is_published = True
        await record_file_change(
            maintenance_db,
            request=request,
            actor=actor,
            file=file,
            details=PlatformContentAuditDetails(
                operation="publish", revision_id=revision.id, previous_revision_id=previous
            ),
        )
        return platform_file_to_read(file, actor)
