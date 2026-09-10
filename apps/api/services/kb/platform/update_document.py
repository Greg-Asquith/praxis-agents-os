# apps/api/services/kb/platform/update_document.py

"""Updates a withdrawn platform knowledge entry."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.kb.platform.utils import (
    get_platform_document,
    platform_session,
    queue_ingestion,
    record_change,
    require_editable,
)
from services.kb.schemas import KBDocumentRead, PlatformKBDocumentUpdateRequest
from services.kb.utils import compute_markdown_hash
from services.kb.write_policy import enforce_platform_kb_write_policy, lock_and_find_kb_duplicate
from utils.content import ContentScope


async def update_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    document_id: UUID,
    payload: PlatformKBDocumentUpdateRequest,
) -> KBDocumentRead:
    async with platform_session(db, actor) as maintenance_db:
        document = await get_platform_document(maintenance_db, document_id, for_update=True)
        require_editable(document)
        if payload.content_md is not None and document.source_type != "manual":
            raise AppValidationError(
                "Only manual knowledge documents can replace their content", field="content_md"
            )
        title = payload.title if payload.title is not None else document.title
        content = payload.content_md if payload.content_md is not None else document.content_md
        duplicate = None
        if content is not None:
            duplicate = await lock_and_find_kb_duplicate(
                maintenance_db,
                workspace_id=None,
                scope=ContentScope.PLATFORM,
                content_hash=compute_markdown_hash(content),
                is_private=False,
                existing_id=document.id,
            )
        enforce_platform_kb_write_policy(
            maintenance_db, title=title, content_md=content, existing=document, duplicate=duplicate
        )
        document.title = title.strip()
        if payload.content_md is not None:
            document.content_md = content
            document.content_hash = compute_markdown_hash(content)
            document.source_updated_at = datetime.now(UTC)
        await queue_ingestion(maintenance_db, document, actor)
        await record_change(
            maintenance_db,
            document=document,
            actor=actor,
            request=request,
            details=PlatformContentAuditDetails(
                operation="update", changed_fields=sorted(payload.model_fields_set)
            ),
        )
        return KBDocumentRead.from_document(document, actor=actor)
