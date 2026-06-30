# apps/api/routes/agents/delete_agent.py

"""Route for soft-deleting a workspace agent."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agents import delete_agent as delete_agent_service

router = APIRouter()


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    agent_id: Annotated[UUID, Path()],
) -> None:
    workspace, membership = workspace_context
    await delete_agent_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        agent_id=agent_id,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
