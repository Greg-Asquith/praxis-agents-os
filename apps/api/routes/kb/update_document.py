# apps/api/routes/kb/update_document.py

"""Update one workspace knowledge document."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.kb.documents import update_document as update_document_service
from services.kb.schemas import KBDocumentRead, KBDocumentUpdateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: Annotated[UUID, Path()],
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: KBDocumentUpdateRequest,
) -> KBDocumentRead:
    workspace, membership = workspace_context
    return await update_document_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        document_id=document_id,
        payload=payload,
    )
