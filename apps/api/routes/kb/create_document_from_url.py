# apps/api/routes/kb/create_document_from_url.py

"""Create a URL-backed workspace knowledge document."""

from fastapi import APIRouter, Depends, Request, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.kb.documents import create_document_from_url as create_document_from_url_service
from services.kb.schemas import KBDocumentRead, KBUrlDocumentCreateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/documents/from-url", status_code=status.HTTP_202_ACCEPTED)
async def create_document_from_url(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: KBUrlDocumentCreateRequest,
) -> KBDocumentRead:
    workspace, membership = workspace_context
    return await create_document_from_url_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
