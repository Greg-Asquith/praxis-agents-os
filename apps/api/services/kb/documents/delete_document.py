# apps/api/services/kb/documents/delete_document.py

"""Soft-delete a knowledge document and remove its retrieval chunks."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.kb import KBChunk
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction
from services.kb.documents.utils import (
    get_mutable_document,
    record_document_audit,
    require_kb_write_access,
    user_provenance,
)
from services.kb.ensure_sweep_job import ensure_kb_sweep_job
from services.kb.utils import document_origin_ref
from services.kb.write_policy import enforce_kb_write_policy


async def delete_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    document_id: UUID,
) -> None:
    require_kb_write_access(membership)
    document = await get_mutable_document(
        db,
        workspace_id=workspace.id,
        user_id=actor.id,
        document_id=document_id,
    )
    enforce_kb_write_policy(
        workspace_id=workspace.id,
        provenance=user_provenance(
            user_id=actor.id,
            source_type=document.source_type,
            origin_ref=document_origin_ref(document),
        ),
        title="Delete knowledge document",
        content_md=None,
        is_private=document.is_private,
        existing=document,
    )
    await db.execute(delete(KBChunk).where(KBChunk.document_id == document.id))
    document.chunk_count = 0
    document.soft_delete(deleted_by=actor.id, cascade=False)
    await ensure_kb_sweep_job(db)
    await db.flush()
    await record_document_audit(
        db,
        request=request,
        actor=actor,
        document=document,
        action=AuditAction.DELETE,
        details={"title": document.title, "source_type": document.source_type},
    )
