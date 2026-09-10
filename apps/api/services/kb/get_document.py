# apps/api/services/kb/get_document.py

"""Read one visible knowledge-base document."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.kb import KBDocument
from services.kb.domain import KB_REFRESHABLE_SOURCE_TYPES, KB_SYNC_READY
from services.kb.schemas import KBDocumentRead
from services.kb.visibility import visible_document_filter


async def get_kb_document(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    document_id: UUID,
) -> KBDocumentRead:
    """Return a visible canonical document without revealing hidden existence."""
    document = await db.scalar(
        select(KBDocument).where(
            KBDocument.id == document_id,
            visible_document_filter(workspace_id, user_id, include_unready_local_sources=True),
        )
    )
    if document is None:
        raise NotFoundError(
            "Knowledge-base document not found",
            resource_type="kb_document",
            resource_id=str(document_id),
        )

    result = KBDocumentRead.from_document(document)
    if (
        document.source_type in KB_REFRESHABLE_SOURCE_TYPES
        and document.source_sync_status != KB_SYNC_READY
    ):
        result.content_md = None
        result.summary = None
    return result
