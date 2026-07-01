# apps/api/routes/agent_runs/get_approval_state.py

"""Route for reading pending approval details for a suspended run."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_runs import get_agent_run_approval_state
from services.agent_runs.schemas import AgentRunApprovalStateResponse

router = APIRouter()


@router.get("/{run_id}/approval-state")
async def get_approval_state(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    run_id: Annotated[UUID, Path()],
) -> AgentRunApprovalStateResponse:
    workspace, _membership = workspace_context
    return await get_agent_run_approval_state(
        db,
        actor=actor,
        workspace=workspace,
        run_id=run_id,
    )
