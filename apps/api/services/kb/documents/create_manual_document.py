# apps/api/services/kb/documents/create_manual_document.py

"""Create a member-authored knowledge document."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction
from services.kb.create_document import create_kb_document
from services.kb.documents.utils import (
    record_document_audit,
    require_kb_write_access,
    user_provenance,
)
from services.kb.domain import KB_SOURCE_MANUAL
from services.kb.schemas import KBDocumentRead, KBManualDocumentCreateRequest


async def create_manual_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: KBManualDocumentCreateRequest,
) -> KBDocumentRead:
    require_kb_write_access(membership)
    provenance = user_provenance(user_id=actor.id, source_type=KB_SOURCE_MANUAL)
    document = await create_kb_document(
        db,
        workspace_id=workspace.id,
        source_type=KB_SOURCE_MANUAL,
        title=payload.title,
        created_by_user_id=actor.id,
        content=payload.content_md,
        is_private=payload.is_private,
        provenance=provenance,
    )
    await record_document_audit(
        db,
        request=request,
        actor=actor,
        document=document,
        action=AuditAction.CREATE,
        details={"source_type": document.source_type, "is_private": document.is_private},
    )
    await db.refresh(document)
    return KBDocumentRead.from_document(document)
