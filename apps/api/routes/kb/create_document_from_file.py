# apps/api/routes/kb/create_document_from_file.py

"""Create a file-backed workspace knowledge document."""

from fastapi import APIRouter, Depends, Request, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.kb.documents import create_document_from_file as create_document_from_file_service
from services.kb.schemas import KBDocumentRead, KBFileDocumentCreateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/documents/from-file", status_code=status.HTTP_202_ACCEPTED)
async def create_document_from_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: KBFileDocumentCreateRequest,
) -> KBDocumentRead:
    workspace, membership = workspace_context
    return await create_document_from_file_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
