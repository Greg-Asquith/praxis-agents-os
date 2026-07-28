# apps/api/routes/agent_runs/list_pending_approvals.py

"""Route for listing the current actor's suspended approval runs."""

from typing import Annotated

from fastapi import APIRouter, Header

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_runs import list_pending_agent_run_approvals
from services.agent_runs.schemas import PendingApprovalsListResponse

router = APIRouter()


@router.get("/pending-approvals")
async def list_pending_approvals(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    workspace_slug: Annotated[str, Header(alias="X-Workspace")],
) -> PendingApprovalsListResponse:
    workspace, _membership = workspace_context
    return await list_pending_agent_run_approvals(
        db,
        actor=actor,
        workspace=workspace,
    )
