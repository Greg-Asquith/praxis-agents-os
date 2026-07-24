# apps/api/services/kb/delete_document.py

"""Soft-delete a knowledge-base document."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.kb import KBDocument
from services.kb.ensure_sweep_job import ensure_kb_sweep_job


async def delete_kb_document(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    document_id: UUID,
    deleted_by: UUID | None = None,
) -> None:
    """Soft-delete one live document without eagerly deleting its chunks."""
    document = await db.scalar(
        select(KBDocument).where(
            KBDocument.id == document_id,
            KBDocument.workspace_id == workspace_id,
            KBDocument.deleted.is_(False),
        )
    )
    if document is None:
        raise NotFoundError(
            "Knowledge-base document not found",
            resource_type="kb_document",
            resource_id=str(document_id),
        )
    document.soft_delete(deleted_by=deleted_by, cascade=False)
    await ensure_kb_sweep_job(db)
