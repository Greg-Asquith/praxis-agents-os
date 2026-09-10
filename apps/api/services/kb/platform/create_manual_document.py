# apps/api/services/kb/platform/create_manual_document.py

"""Creates an unpublished platform manual entry."""

from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.kb import KBDocument
from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.kb.platform.utils import (
    platform_session,
    queue_ingestion,
    record_change,
)
from services.kb.schemas import KBDocumentRead, PlatformKBManualDocumentCreateRequest
from services.kb.utils import compute_markdown_hash
from services.kb.write_policy import enforce_platform_kb_write_policy, lock_and_find_kb_duplicate
from utils.content import ContentScope


async def create_manual_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    payload: PlatformKBManualDocumentCreateRequest,
) -> KBDocumentRead:
    async with platform_session(db, actor) as maintenance_db:
        content_hash = compute_markdown_hash(payload.content_md)
        duplicate = await lock_and_find_kb_duplicate(
            maintenance_db,
            workspace_id=None,
            scope=ContentScope.PLATFORM,
            content_hash=content_hash,
            is_private=False,
        )
        enforce_platform_kb_write_policy(
            maintenance_db, title=payload.title, content_md=payload.content_md, duplicate=duplicate
        )
        document = KBDocument(
            scope=ContentScope.PLATFORM,
            workspace_id=None,
            is_published=False,
            title=payload.title.strip(),
            source_type="manual",
            source_updated_at=datetime.now(UTC),
            content_md=payload.content_md,
            content_hash=content_hash,
            is_private=False,
            created_by_user_id=actor.id,
            annotation_enabled=False,
            meta={},
        )
        maintenance_db.add(document)
        await queue_ingestion(maintenance_db, document, actor)
        await record_change(
            maintenance_db,
            document=document,
            actor=actor,
            request=request,
            details=PlatformContentAuditDetails(operation="create"),
        )
        return KBDocumentRead.from_document(document, actor=actor)
