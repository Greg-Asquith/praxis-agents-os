# apps/api/routes/agents/list_agents.py

"""Route for listing workspace agents."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.agents import list_agents as list_agents_service
from services.agents.schemas import AgentsListResponse

router = APIRouter()


@router.get("/")
async def list_agents(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_inactive: bool = False,
) -> AgentsListResponse:
    workspace, _membership = workspace_context
    return await list_agents_service(
        db,
        workspace=workspace,
        limit=limit,
        offset=offset,
        include_inactive=include_inactive,
    )
