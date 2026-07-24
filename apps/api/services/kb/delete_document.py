# apps/api/services/kb/delete_document.py

"""Soft-delete a knowledge-base document."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.kb import KBChunk, KBDocument
from services.kb.domain import KB_SOURCE_UPLOAD
from services.kb.ensure_sweep_job import ensure_kb_sweep_job
from services.kb.write_policy import KBProvenance, enforce_kb_write_policy


async def delete_kb_document(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    document_id: UUID,
    deleted_by: UUID | None = None,
) -> None:
    """Soft-delete one live document and remove its retrieval chunks."""
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
    origin_ref = (
        str(document.file_revision_id)
        if document.source_type == KB_SOURCE_UPLOAD and document.file_revision_id
        else document.external_url
    )
    enforce_kb_write_policy(
        workspace_id=workspace_id,
        provenance=KBProvenance(
            actor_kind="user" if deleted_by else "system",
            user_id=deleted_by,
            source_type=document.source_type,
            origin_ref=origin_ref,
        ),
        title="Delete knowledge document",
        content_md=None,
        is_private=document.is_private,
        existing=document,
    )
    await db.execute(delete(KBChunk).where(KBChunk.document_id == document.id))
    document.chunk_count = 0
    document.soft_delete(deleted_by=deleted_by, cascade=False)
    await ensure_kb_sweep_job(db)
