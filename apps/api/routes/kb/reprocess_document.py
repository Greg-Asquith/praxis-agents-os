# apps/api/routes/kb/reprocess_document.py

"""Reprocess one workspace knowledge document."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.kb.documents import reprocess_document as reprocess_document_service
from services.kb.schemas import KBDocumentRead

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post(
    "/documents/{document_id}/reprocess",
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess_document(
    document_id: Annotated[UUID, Path()],
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> KBDocumentRead:
    workspace, membership = workspace_context
    return await reprocess_document_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        document_id=document_id,
    )
