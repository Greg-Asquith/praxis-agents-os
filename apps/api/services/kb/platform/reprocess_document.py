# apps/api/services/kb/platform/reprocess_document.py

"""Queues a withdrawn platform entry for ingestion."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.kb.platform.utils import (
    get_platform_document,
    platform_session,
    queue_ingestion,
    record_change,
    require_editable,
)
from services.kb.schemas import KBDocumentRead


async def reprocess_document(
    db: AsyncSession, *, request: Request, actor: User, document_id: UUID
) -> KBDocumentRead:
    async with platform_session(db, actor) as maintenance_db:
        document = await get_platform_document(maintenance_db, document_id, for_update=True)
        require_editable(document)
        await queue_ingestion(maintenance_db, document, actor)
        await record_change(
            maintenance_db,
            document=document,
            actor=actor,
            request=request,
            details=PlatformContentAuditDetails(operation="update", changed_fields=["status"]),
        )
        return KBDocumentRead.from_document(document, actor=actor)
