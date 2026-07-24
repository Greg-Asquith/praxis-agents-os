# apps/api/services/kb/documents/reprocess_document.py

"""Queue a knowledge document for fresh ingestion."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction
from services.jobs.enqueue_job import enqueue_job
from services.kb.documents.utils import (
    get_mutable_document,
    record_document_audit,
    require_kb_write_access,
    user_provenance,
)
from services.kb.domain import KB_STATUS_PENDING, KB_STATUS_PROCESSING
from services.kb.schemas import KBDocumentRead
from services.kb.utils import document_origin_ref
from services.kb.write_policy import enforce_kb_write_policy


async def reprocess_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    document_id: UUID,
) -> KBDocumentRead:
    require_kb_write_access(membership)
    document = await get_mutable_document(
        db,
        workspace_id=workspace.id,
        user_id=actor.id,
        document_id=document_id,
    )
    if document.status in {KB_STATUS_PENDING, KB_STATUS_PROCESSING}:
        raise ConflictError(
            "Knowledge document processing is already in progress",
            conflicting_resource=str(document.id),
        )
    enforce_kb_write_policy(
        workspace_id=workspace.id,
        provenance=user_provenance(
            user_id=actor.id,
            source_type=document.source_type,
            origin_ref=document_origin_ref(document),
        ),
        title=document.title,
        content_md=document.content_md,
        is_private=document.is_private,
        existing=document,
    )
    document.status = KB_STATUS_PENDING
    document.processing_error = None
    document.processing_attempts = 0
    await enqueue_job(
        db,
        kind="kb.ingest_document",
        workspace_id=workspace.id,
        subject_type="kb_document",
        subject_id=document.id,
        initiated_by_user_id=actor.id,
    )
    await db.flush()
    await record_document_audit(
        db,
        request=request,
        actor=actor,
        document=document,
        action=AuditAction.EXECUTE,
        details={"operation": "reprocess", "source_type": document.source_type},
    )
    await db.refresh(document)
    return KBDocumentRead.from_document(document)
