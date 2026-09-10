# apps/api/services/kb/platform/utils.py

"""Authority, document locks, and audit helpers for platform knowledge."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.dependencies import require_super_admin_user
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError, NotFoundError
from models.kb import KBChunk, KBDocument
from models.user import User
from services.audit_events import AuditResourceType
from services.audit_events.platform_content_events import (
    PlatformContentAuditDetails,
    record_platform_content_audit_event,
)
from services.jobs.enqueue_job import enqueue_job
from utils.content import ContentScope


@asynccontextmanager
async def platform_session(db: AsyncSession, actor: User) -> AsyncIterator[AsyncSession]:
    require_super_admin_user(actor)
    await db.commit()
    async with maintenance_async_db_session() as maintenance_db:
        live_actor = await maintenance_db.get(User, actor.id, populate_existing=True)
        if live_actor is None or live_actor.deleted or not live_actor.is_active:
            raise AuthorizationError("Platform knowledge requires an active super admin")
        require_super_admin_user(live_actor)
        yield maintenance_db


async def get_platform_document(
    db: AsyncSession, document_id: UUID, *, for_update: bool = False
) -> KBDocument:
    statement = select(KBDocument).where(
        KBDocument.id == document_id,
        KBDocument.scope == ContentScope.PLATFORM,
        KBDocument.workspace_id.is_(None),
        KBDocument.deleted.is_(False),
    )
    if for_update:
        statement = statement.with_for_update()
    document = await db.scalar(statement)
    if document is None:
        raise NotFoundError(
            "Knowledge document not found",
            resource_type="kb_document",
            resource_id=str(document_id),
        )
    return document


def require_editable(document: KBDocument) -> None:
    if document.is_published:
        raise ConflictError(
            "Withdraw the platform knowledge document before editing or reprocessing",
            conflicting_resource=str(document.id),
        )
    if document.status in {"pending", "processing"}:
        raise ConflictError(
            "Knowledge document processing is already in progress",
            conflicting_resource=str(document.id),
        )


async def queue_ingestion(db: AsyncSession, document: KBDocument, actor: User) -> None:
    await db.execute(delete(KBChunk).where(KBChunk.document_id == document.id))
    document.chunk_count = 0
    document.summary = None
    version = str(uuid4())
    document.meta = {
        **(document.meta or {}),
        "ingestion_version": version,
        "embedding_status": "pending",
        "embedding_error": None,
    }
    document.status = "pending"
    document.processing_error = None
    document.processing_attempts = 0
    await db.flush()
    await enqueue_job(
        db,
        kind="kb.platform_ingest_document",
        concurrency_user_id=actor.id,
        subject_type="kb_document",
        subject_id=document.id,
        initiated_by_user_id=actor.id,
        payload={"version": version},
    )


async def record_change(
    db: AsyncSession,
    *,
    document: KBDocument,
    actor: User,
    request: Request,
    details: PlatformContentAuditDetails,
) -> None:
    await db.flush()
    await record_platform_content_audit_event(
        db,
        request=request,
        actor=actor,
        resource_type=AuditResourceType.KB_DOCUMENT,
        resource_id=document.id,
        details=details,
    )
    await db.refresh(document)
