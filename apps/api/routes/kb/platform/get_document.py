# apps/api/routes/kb/platform/get_document.py

"""Gets document through super-admin platform management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import get_document as service
from services.kb.schemas import KBDocumentRead

router = APIRouter()


@router.get("/{document_id}")
async def get_document(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    document_id: Annotated[UUID, Path()],
) -> KBDocumentRead:
    return await service(db, actor=actor, document_id=document_id)
