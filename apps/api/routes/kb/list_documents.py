# apps/api/routes/kb/list_documents.py

"""List workspace knowledge documents."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_read,
)
from services.kb.documents import list_documents as list_documents_service
from services.kb.schemas import KBDocumentsListResponse

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/documents")
async def list_documents(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    workspace_slug: Annotated[str, Header(alias="X-Workspace")],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    source_type: Literal["upload", "url", "manual", "conversation", "integration"] | None = None,
    status: Literal["pending", "processing", "ready", "error"] | None = None,
    is_private: bool | None = None,
) -> KBDocumentsListResponse:
    workspace, _membership = workspace_context
    return await list_documents_service(
        db,
        actor=actor,
        workspace=workspace,
        limit=limit,
        offset=offset,
        source_type=source_type,
        status=status,
        is_private=is_private,
    )
