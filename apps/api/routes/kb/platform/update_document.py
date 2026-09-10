# apps/api/routes/kb/platform/update_document.py

"""Updates document through super-admin platform management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import update_document as service
from services.kb.schemas import KBDocumentRead, PlatformKBDocumentUpdateRequest

router = APIRouter()


@router.patch("/{document_id}")
async def update_document(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    document_id: Annotated[UUID, Path()],
    payload: PlatformKBDocumentUpdateRequest,
) -> KBDocumentRead:
    return await service(db, actor=actor, request=request, document_id=document_id, payload=payload)
