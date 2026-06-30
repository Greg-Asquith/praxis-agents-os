# apps/api/routes/agents/update_agent.py

"""Route for updating a workspace agent."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agents import update_agent as update_agent_service
from services.agents.schemas import AgentRead, AgentUpdateRequest

router = APIRouter()


@router.patch("/{agent_id}")
async def update_agent(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    agent_id: Annotated[UUID, Path()],
    payload: AgentUpdateRequest,
) -> AgentRead:
    workspace, membership = workspace_context
    return await update_agent_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        agent_id=agent_id,
        payload=payload,
    )
