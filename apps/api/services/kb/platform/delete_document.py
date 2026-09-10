# apps/api/services/kb/platform/delete_document.py

"""Deletes a platform knowledge entry."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.kb.platform.utils import get_platform_document, platform_session, record_change


async def delete_document(
    db: AsyncSession, *, request: Request, actor: User, document_id: UUID
) -> None:
    async with platform_session(db, actor) as maintenance_db:
        document = await get_platform_document(maintenance_db, document_id, for_update=True)
        document.is_published = False
        document.soft_delete(deleted_by=actor.id)
        await record_change(
            maintenance_db,
            document=document,
            actor=actor,
            request=request,
            details=PlatformContentAuditDetails(operation="delete"),
        )
