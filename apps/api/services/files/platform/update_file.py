# apps/api/services/files/platform/update_file.py

"""Updates platform File metadata under super-admin authority."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.files.domain import FileRead, PlatformFileUpdateRequest
from services.files.platform.utils import (
    get_platform_file,
    platform_file_to_read,
    platform_session,
    record_file_change,
)
from services.files.utils import apply_file_metadata_update


async def update_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    file_id: UUID,
    payload: PlatformFileUpdateRequest,
) -> FileRead:
    """Updates metadata and records changed fields in the same transaction."""
    async with platform_session(db, actor=actor) as platform_db:
        file = await get_platform_file(platform_db, file_id=file_id, for_update=True)
        changed_fields = apply_file_metadata_update(
            file,
            name=payload.name,
            description=payload.description,
            fields_set=payload.model_fields_set,
        )
        if changed_fields:
            await record_file_change(
                platform_db,
                request=request,
                actor=actor,
                file=file,
                details=PlatformContentAuditDetails(
                    operation="update", changed_fields=changed_fields
                ),
            )
        return platform_file_to_read(file, actor=actor)
