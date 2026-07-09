# apps/api/routes/agent_runs/cancel_run.py

"""Route for cancelling an active or suspended agent run."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_runs import request_agent_run_cancellation
from services.agent_runs.schemas import AgentRunCancelResponse

router = APIRouter()


@router.post("/{run_id}/cancel")
async def cancel_run(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    run_id: Annotated[UUID, Path()],
    request: Request,
) -> AgentRunCancelResponse:
    workspace, membership = workspace_context
    return await request_agent_run_cancellation(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        run_id=run_id,
        request=request,
    )
