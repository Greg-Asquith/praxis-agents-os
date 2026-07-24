# apps/api/services/kb/documents/create_document_from_file.py

"""Create a knowledge document pinned to a workspace file revision."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction
from services.files.utils import get_file_for_workspace
from services.kb.create_document import create_kb_document
from services.kb.documents.utils import (
    record_document_audit,
    require_kb_write_access,
    user_provenance,
)
from services.kb.domain import KB_SOURCE_UPLOAD
from services.kb.schemas import KBDocumentRead, KBFileDocumentCreateRequest


async def create_document_from_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: KBFileDocumentCreateRequest,
) -> KBDocumentRead:
    require_kb_write_access(membership)
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=payload.file_id,
    )
    revision_id = file.current_revision_id
    if revision_id is None:
        raise RuntimeError("Workspace file has no current revision")
    title = payload.title or file.name
    provenance = user_provenance(
        user_id=actor.id,
        source_type=KB_SOURCE_UPLOAD,
        origin_ref=str(revision_id),
    )
    document = await create_kb_document(
        db,
        workspace_id=workspace.id,
        source_type=KB_SOURCE_UPLOAD,
        title=title,
        created_by_user_id=actor.id,
        file_revision_id=revision_id,
        is_private=payload.is_private,
        provenance=provenance,
    )
    await record_document_audit(
        db,
        request=request,
        actor=actor,
        document=document,
        action=AuditAction.CREATE,
        details={
            "source_type": document.source_type,
            "is_private": document.is_private,
            "file_id": str(file.id),
            "file_revision_id": str(revision_id),
        },
    )
    await db.refresh(document)
    return KBDocumentRead.from_document(document)
