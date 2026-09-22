# apps/api/routes/agent_runs/review_approval.py

"""Route for retaining changed approval selections before approval."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_runs.review_approval import review_agent_run_approval
from services.agent_runs.schemas import AgentRunApprovalStateResponse, AgentRunReviewApprovalRequest

router = APIRouter()


@router.post("/{run_id}/review-approval", response_model_exclude_none=True)
async def review_approval(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    run_id: Annotated[UUID, Path()],
    payload: AgentRunReviewApprovalRequest,
) -> AgentRunApprovalStateResponse:
    workspace, membership = workspace_context
    return await review_agent_run_approval(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        run_id=run_id,
        payload=payload,
    )
