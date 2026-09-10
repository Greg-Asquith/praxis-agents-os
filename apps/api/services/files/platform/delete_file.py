# apps/api/services/files/platform/delete_file.py

"""Deletes a platform File into the existing retention lifecycle."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.files.platform.utils import get_platform_file, platform_session, record_file_change


async def delete_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    file_id: UUID,
) -> None:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id, for_update=True)
        file.is_published = False
        file.soft_delete(deleted_by=actor.id)
        await record_file_change(
            maintenance_db,
            request=request,
            actor=actor,
            file=file,
            details=PlatformContentAuditDetails(
                operation="delete", revision_id=file.current_revision_id
            ),
        )
