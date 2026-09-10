# apps/api/services/kb/platform/list_documents.py

"""Lists platform knowledge drafts for super-admin review."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.kb import KBDocument
from models.user import User
from services.kb.platform.utils import platform_session
from services.kb.schemas import KBDocumentListItem, KBDocumentsListResponse
from utils.content import ContentScope
from utils.pagination import paginate


async def list_documents(
    db: AsyncSession, *, actor: User, limit: int = 50, offset: int = 0
) -> KBDocumentsListResponse:
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    async with platform_session(db, actor) as maintenance_db:
        documents, total = await paginate(
            maintenance_db,
            select(KBDocument).where(
                KBDocument.scope == ContentScope.PLATFORM,
                KBDocument.workspace_id.is_(None),
                KBDocument.deleted.is_(False),
            ),
            KBDocument.updated_at.desc(),
            KBDocument.id.desc(),
            limit=limit,
            offset=offset,
        )
        return KBDocumentsListResponse(
            documents=[
                KBDocumentListItem.from_document(document, actor=actor) for document in documents
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
