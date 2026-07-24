# apps/api/services/kb/get_document.py

"""Read one visible knowledge-base document."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.kb import KBDocument
from services.kb.schemas import KBDocumentRead


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
            KBDocument.workspace_id == workspace_id,
            KBDocument.deleted_at.is_(None),
            or_(
                KBDocument.is_private.is_(False),
                KBDocument.created_by_user_id == user_id,
            ),
        )
    )
    if document is None:
        raise NotFoundError(
            "Knowledge-base document not found",
            resource_type="kb_document",
            resource_id=str(document_id),
        )

    return KBDocumentRead(
        id=document.id,
        title=document.title,
        concept_id=document.concept_id,
        source_type=document.source_type,
        source_updated_at=document.source_updated_at,
        status=document.status,
        summary=document.summary,
        external_url=document.external_url,
        is_private=document.is_private,
        chunk_count=document.chunk_count,
        content_md=document.content_md,
        meta=document.meta,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )
