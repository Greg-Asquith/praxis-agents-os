# apps/api/services/kb/platform/withdraw_document.py

"""Withdraws a platform knowledge entry."""

from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.kb.platform.utils import get_platform_document, platform_session, record_change
from services.kb.schemas import KBDocumentRead


async def withdraw_document(
    db: AsyncSession, *, request: Request, actor: User, document_id: UUID
) -> KBDocumentRead:
    async with platform_session(db, actor) as maintenance_db:
        document = await get_platform_document(maintenance_db, document_id, for_update=True)
        document.is_published = False
        document.meta = {**document.meta, "ingestion_version": str(uuid4())}
        if document.status in {"pending", "processing"}:
            document.status = "error"
            document.processing_error = "Processing cancelled by withdrawal; reprocess to continue"
        await record_change(
            maintenance_db,
            document=document,
            actor=actor,
            request=request,
            details=PlatformContentAuditDetails(operation="withdraw"),
        )
        return KBDocumentRead.from_document(document, actor=actor)
