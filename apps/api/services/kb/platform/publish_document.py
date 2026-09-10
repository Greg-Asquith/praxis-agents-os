# apps/api/services/kb/platform/publish_document.py

"""Publishes a reviewed, processed platform knowledge entry."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.kb import KBChunk
from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.kb.platform.utils import get_platform_document, platform_session, record_change
from services.kb.schemas import KBDocumentRead, PlatformKBDocumentPublishRequest
from services.kb.utils import compute_markdown_hash


async def publish_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    document_id: UUID,
    payload: PlatformKBDocumentPublishRequest,
) -> KBDocumentRead:
    async with platform_session(db, actor) as maintenance_db:
        document = await get_platform_document(maintenance_db, document_id, for_update=True)
        if document.meta.get("ingestion_version") != payload.expected_ingestion_version:
            raise ConflictError(
                "Knowledge document has changed; review it again",
                conflicting_resource=str(document.id),
            )
        chunk_count = await maintenance_db.scalar(
            select(func.count()).select_from(KBChunk).where(KBChunk.document_id == document.id)
        )
        if (
            document.status != "ready"
            or document.processing_attempts < 1
            or not (document.content_md or "").strip()
            or document.content_hash != compute_markdown_hash(document.content_md or "")
            or document.chunk_count < 1
            or chunk_count != document.chunk_count
        ):
            raise ConflictError(
                "Knowledge document processing must finish before publication",
                conflicting_resource=str(document.id),
            )
        if not document.is_published:
            document.is_published = True
            await record_change(
                maintenance_db,
                document=document,
                actor=actor,
                request=request,
                details=PlatformContentAuditDetails(operation="publish"),
            )
        return KBDocumentRead.from_document(document, actor=actor)
