# apps/api/routes/agents/get_agent.py

"""Route for reading a workspace agent."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.agents import get_agent as get_agent_service
from services.agents.schemas import AgentRead

router = APIRouter()


@router.get("/{agent_id}")
async def get_agent(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    agent_id: Annotated[UUID, Path()],
) -> AgentRead:
    workspace, _membership = workspace_context
    return await get_agent_service(db, workspace=workspace, agent_id=agent_id)
