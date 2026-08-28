# apps/api/routes/kb/create_document_from_integration.py

"""Import an integration source as a workspace knowledge document."""

from fastapi import APIRouter, Depends, Request, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.kb.integration_sources import import_integration_document
from services.kb.schemas import KBDocumentRead, KBIntegrationDocumentCreateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/documents/from-integration", status_code=status.HTTP_202_ACCEPTED)
async def create_document_from_integration(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: KBIntegrationDocumentCreateRequest,
) -> KBDocumentRead:
    workspace, membership = workspace_context
    return await import_integration_document(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
