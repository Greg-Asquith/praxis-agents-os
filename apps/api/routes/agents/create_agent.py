# apps/api/routes/agents/create_agent.py

"""Route for creating a workspace agent."""

from fastapi import APIRouter, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agents import create_agent as create_agent_service
from services.agents.schemas import AgentCreateRequest, AgentRead

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_agent(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: AgentCreateRequest,
) -> AgentRead:
    workspace, membership = workspace_context
    return await create_agent_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
