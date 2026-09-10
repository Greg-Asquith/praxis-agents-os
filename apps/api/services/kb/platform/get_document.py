# apps/api/services/kb/platform/get_document.py

"""Reads a platform knowledge draft for a super admin."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.kb.platform.utils import get_platform_document, platform_session
from services.kb.schemas import KBDocumentRead


async def get_document(db: AsyncSession, *, actor: User, document_id: UUID) -> KBDocumentRead:
    async with platform_session(db, actor) as maintenance_db:
        document = await get_platform_document(maintenance_db, document_id)
        return KBDocumentRead.from_document(document, actor=actor)
