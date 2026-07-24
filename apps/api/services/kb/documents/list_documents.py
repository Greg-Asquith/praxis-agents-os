# apps/api/services/kb/documents/list_documents.py

"""List visible knowledge documents in a workspace."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.kb import KBDocument
from models.user import User
from models.workspace import Workspace
from services.kb.schemas import (
    KBDocumentListItem,
    KBDocumentsListResponse,
)
from utils.pagination import paginate


async def list_documents(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    limit: int,
    offset: int,
    source_type: str | None,
    status: str | None,
    is_private: bool | None,
) -> KBDocumentsListResponse:
    filters = [
        KBDocument.workspace_id == workspace.id,
        KBDocument.deleted.is_(False),
        or_(
            KBDocument.is_private.is_(False),
            KBDocument.created_by_user_id == actor.id,
        ),
    ]
    if source_type is not None:
        filters.append(KBDocument.source_type == source_type)
    if status is not None:
        filters.append(KBDocument.status == status)
    if is_private is not None:
        filters.append(KBDocument.is_private == is_private)

    documents, total = await paginate(
        db,
        select(KBDocument).where(*filters),
        KBDocument.updated_at.desc(),
        KBDocument.id.desc(),
        limit=limit,
        offset=offset,
    )
    return KBDocumentsListResponse(
        documents=[KBDocumentListItem.from_document(document) for document in documents],
        total=total,
        limit=limit,
        offset=offset,
    )
