# apps/api/routes/kb/create_document.py

"""Create a manual workspace knowledge document."""

from fastapi import APIRouter, Depends, Request, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.kb.documents import create_manual_document as create_manual_document_service
from services.kb.schemas import KBDocumentRead, KBManualDocumentCreateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def create_document(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: KBManualDocumentCreateRequest,
) -> KBDocumentRead:
    workspace, membership = workspace_context
    return await create_manual_document_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
