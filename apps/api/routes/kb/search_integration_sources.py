# apps/api/routes/kb/search_integration_sources.py

"""Search an integration resource for Knowledge Base sources."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.integrations.plugin import KnowledgeSourceSearchResult
from services.kb.integration_sources import search_integration_knowledge_sources

router = APIRouter(dependencies=[Depends(require_editor)])


@router.get("/integration-sources/search")
async def search_sources(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    integration_resource_id: Annotated[UUID, Query()],
    query: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> tuple[KnowledgeSourceSearchResult, ...]:
    workspace, membership = workspace_context
    return await search_integration_knowledge_sources(
        db,
        integration_resource_id=integration_resource_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
        query=query,
        limit=limit,
    )
