# apps/api/services/kb/platform/create_document_from_file.py

"""Pins a platform upload entry to the reviewed platform File revision."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.kb import KBDocument
from models.user import User
from services.audit_events.platform_content_events import PlatformContentAuditDetails
from services.files.contract import contract_for_content_type
from services.files.platform.utils import get_platform_file, get_platform_revision
from services.kb.platform.utils import (
    platform_session,
    queue_ingestion,
    record_change,
)
from services.kb.schemas import KBDocumentRead, PlatformKBFileDocumentCreateRequest
from services.kb.write_policy import enforce_platform_kb_write_policy
from utils.content import ContentScope


async def create_document_from_file(
    db: AsyncSession, *, request: Request, actor: User, payload: PlatformKBFileDocumentCreateRequest
) -> KBDocumentRead:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=payload.file_id, for_update=True)
        revision = await get_platform_revision(
            maintenance_db, file=file, revision_id=payload.file_revision_id
        )
        entry = contract_for_content_type(revision.content_type)
        if not entry.editable and not (entry.ingestible and revision.markdown_object_key):
            raise AppValidationError(
                "File processing must finish before importing knowledge", field="file_revision_id"
            )
        title = payload.title or file.name
        enforce_platform_kb_write_policy(maintenance_db, title=title, content_md=None)
        document = KBDocument(
            scope=ContentScope.PLATFORM,
            workspace_id=None,
            is_published=False,
            title=title.strip(),
            source_type="upload",
            file_revision_id=revision.id,
            content_hash="",
            is_private=False,
            created_by_user_id=actor.id,
            annotation_enabled=True,
            meta={},
        )
        maintenance_db.add(document)
        await queue_ingestion(maintenance_db, document, actor)
        await record_change(
            maintenance_db,
            document=document,
            actor=actor,
            request=request,
            details=PlatformContentAuditDetails(operation="create", revision_id=revision.id),
        )
        return KBDocumentRead.from_document(document, actor=actor)
