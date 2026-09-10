# apps/api/services/files/platform/withdraw_file.py

"""Withdraws a platform File while retaining immutable publication history."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.files.domain import FileRead
from services.files.platform.utils import (
    get_platform_file,
    platform_file_to_read,
    platform_session,
    record_file_change,
)


async def withdraw_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    file_id: UUID,
) -> FileRead:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id, for_update=True)
        if file.is_published:
            file.is_published = False
            await record_file_change(
                maintenance_db,
                request=request,
                actor=actor,
                file=file,
                details=PlatformContentAuditDetails(
                    operation="withdraw", revision_id=file.published_revision_id
                ),
            )
        return platform_file_to_read(file, actor)
