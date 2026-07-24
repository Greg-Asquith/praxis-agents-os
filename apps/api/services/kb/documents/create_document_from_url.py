# apps/api/services/kb/documents/create_document_from_url.py

"""Create an externally fetched knowledge document source."""

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
from services.kb.domain import KB_SOURCE_URL
from services.kb.schemas import KBDocumentRead, KBUrlDocumentCreateRequest
from services.kb.utils import validate_source_url


async def create_document_from_url(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: KBUrlDocumentCreateRequest,
) -> KBDocumentRead:
    require_kb_write_access(membership)
    normalized_url = validate_source_url(payload.url)
    provenance = user_provenance(
        user_id=actor.id,
        source_type=KB_SOURCE_URL,
        origin_ref=normalized_url,
    )
    document = await create_kb_document(
        db,
        workspace_id=workspace.id,
        source_type=KB_SOURCE_URL,
        title=payload.title,
        created_by_user_id=actor.id,
        url=normalized_url,
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
