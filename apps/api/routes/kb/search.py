# apps/api/routes/kb/search.py

"""Search visible knowledge-base chunks."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_read,
)
from services.kb import search_chunks as search_chunks_service
from services.kb.schemas import KBSearchResult

router = APIRouter(dependencies=[Depends(require_read)])


class KBSearchRequest(BaseModel):
    """Knowledge-base search request."""

    query: str = Field(min_length=1, max_length=1_000)
    top_k: int | None = None
    source_types: list[str] | None = None
    document_ids: list[UUID] | None = None
    private_only: bool = False


@router.post("/search")
async def search_kb(
    body: KBSearchRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    workspace_slug: Annotated[str, Header(alias="X-Workspace")],
) -> KBSearchResult:
    workspace, _membership = workspace_context
    return await search_chunks_service(
        db,
        workspace_id=workspace.id,
        user_id=actor.id,
        query=body.query,
        top_k=body.top_k,
        source_types=body.source_types,
        document_ids=body.document_ids,
        private_only=body.private_only,
    )
