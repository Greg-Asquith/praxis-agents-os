# apps/api/services/files/platform/restore_file_revision.py

"""Restores platform File content into a new draft revision."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.files.domain import FileRead, FileRestoreRequest
from services.files.platform.utils import (
    get_platform_file,
    get_platform_revision,
    platform_file_to_read,
    platform_session,
    record_file_change,
)
from services.files.utils import append_restore_revision


async def restore_file_revision(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    file_id: UUID,
    payload: FileRestoreRequest,
) -> FileRead:
    """Appends a draft from an authorised revision without changing publication."""
    async with platform_session(db, actor=actor) as platform_db:
        file = await get_platform_file(platform_db, file_id=file_id, for_update=True)
        if file.current_revision_id != payload.expected_current_revision_id:
            raise ConflictError(
                "File has changed",
                conflicting_resource="file",
                details={"current_revision_id": str(file.current_revision_id)},
            )
        if payload.revision_id == file.current_revision_id:
            raise AppValidationError("Cannot restore the current revision", field="revision_id")
        source = await get_platform_revision(
            platform_db, file=file, revision_id=payload.revision_id
        )
        previous_revision_id = file.current_revision_id
        revision = await append_restore_revision(platform_db, file=file, source=source, actor=actor)
        await record_file_change(
            platform_db,
            request=request,
            actor=actor,
            file=file,
            details=PlatformContentAuditDetails(
                operation="restore",
                revision_id=revision.id,
                previous_revision_id=previous_revision_id,
            ),
        )
        return platform_file_to_read(file, actor=actor)
