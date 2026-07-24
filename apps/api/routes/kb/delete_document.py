# apps/api/routes/kb/delete_document.py

"""Delete one workspace knowledge document."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.kb.documents import delete_document as delete_document_service

router = APIRouter(dependencies=[Depends(require_editor)])


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: Annotated[UUID, Path()],
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> Response:
    workspace, membership = workspace_context
    await delete_document_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        document_id=document_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
