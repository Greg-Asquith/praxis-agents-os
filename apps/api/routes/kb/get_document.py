# apps/api/routes/kb/get_document.py

"""Read one visible canonical knowledge-base document."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_read,
)
from services.kb import get_kb_document as get_kb_document_service
from services.kb.schemas import KBDocumentRead

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/documents/{document_id}")
async def get_kb_document(
    document_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    workspace_slug: Annotated[str, Header(alias="X-Workspace")],
) -> KBDocumentRead:
    workspace, _membership = workspace_context
    return await get_kb_document_service(
        db,
        workspace_id=workspace.id,
        user_id=actor.id,
        document_id=document_id,
    )
