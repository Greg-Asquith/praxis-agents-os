# apps/api/services/kb/documents/update_document.py

"""Update editable knowledge-document fields."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
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
from services.kb.domain import KB_SOURCE_MANUAL, KB_STATUS_PENDING
from services.kb.schemas import KBDocumentRead, KBDocumentUpdateRequest
from services.kb.utils import compute_markdown_hash, document_origin_ref
from services.kb.write_policy import enforce_kb_write_policy, lock_and_find_kb_duplicate


async def update_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    document_id: UUID,
    payload: KBDocumentUpdateRequest,
) -> KBDocumentRead:
    require_kb_write_access(membership)
    document = await get_mutable_document(
        db,
        workspace_id=workspace.id,
        user_id=actor.id,
        document_id=document_id,
    )

    content_changed = "content_md" in payload.model_fields_set
    if content_changed and document.source_type != KB_SOURCE_MANUAL:
        raise AppValidationError(
            "Only manual knowledge documents can replace their content",
            field="content_md",
        )

    title = payload.title if "title" in payload.model_fields_set else document.title
    content_md = payload.content_md if content_changed else document.content_md
    is_private = (
        payload.is_private if "is_private" in payload.model_fields_set else document.is_private
    )
    duplicate = None
    if content_md is not None and (content_changed or "is_private" in payload.model_fields_set):
        new_hash = compute_markdown_hash(content_md)
        duplicate = await lock_and_find_kb_duplicate(
            db,
            workspace_id=workspace.id,
            content_hash=new_hash,
            is_private=is_private,
            existing_id=document.id,
        )

    enforce_kb_write_policy(
        workspace_id=workspace.id,
        provenance=user_provenance(
            user_id=actor.id,
            source_type=document.source_type,
            origin_ref=document_origin_ref(document),
        ),
        title=title,
        content_md=content_md,
        is_private=is_private,
        existing=document,
        duplicate=duplicate,
    )

    changed_fields: list[str] = []
    if document.title != title:
        document.title = title.strip()
        changed_fields.append("title")
    if document.is_private != is_private:
        document.is_private = is_private
        changed_fields.append("is_private")
    if content_changed and document.content_md != content_md:
        document.content_md = content_md
        document.source_updated_at = datetime.now(UTC)
        document.status = KB_STATUS_PENDING
        document.processing_error = None
        document.processing_attempts = 0
        changed_fields.append("content_md")
        await enqueue_job(
            db,
            kind="kb.ingest_document",
            workspace_id=workspace.id,
            subject_type="kb_document",
            subject_id=document.id,
            initiated_by_user_id=actor.id,
        )

    if changed_fields:
        await db.flush()
        await record_document_audit(
            db,
            request=request,
            actor=actor,
            document=document,
            action=AuditAction.UPDATE,
            details={"changed_fields": changed_fields},
        )
        await db.refresh(document)
    return KBDocumentRead.from_document(document)
