# apps/api/routes/kb/platform/list_documents.py

"""Lists documents through super-admin platform management."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import list_documents as service
from services.kb.schemas import KBDocumentsListResponse

router = APIRouter()


@router.get("/")
async def list_documents(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KBDocumentsListResponse:
    return await service(db, actor=actor, limit=limit, offset=offset)
