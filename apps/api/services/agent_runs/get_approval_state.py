# apps/api/services/agent_runs/get_approval_state.py

"""Read the safe pending approval projection for an agent run."""

from uuid import UUID

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.schemas import (
    AgentRunApprovalStateResponse,
    PendingToolApprovalRead,
)
from services.agents.runtime.approval_state import load_suspended_run_state


async def get_agent_run_approval_state(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    run_id: UUID,
) -> AgentRunApprovalStateResponse:
    """Return pending approval descriptors without exposing run message history."""
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
            AgentRun.deleted == False,  # noqa: E712
        )
    )
    if run is None:
        raise NotFoundError(
            "Agent run not found",
            resource_type="agent_run",
            resource_id=str(run_id),
        )

    if run.status != RUN_STATUS_AWAITING_APPROVAL:
        raise ConflictError(
            "Agent run is not awaiting approval",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    suspended_state = load_suspended_run_state(run)
    return AgentRunApprovalStateResponse(
        run_id=run.id,
        conversation_id=run.conversation_id,
        approvals=[
            PendingToolApprovalRead(
                tool_call_id=approval.tool_call_id,
                name=approval.tool_name,
                args=to_jsonable_python(approval.args),
            )
            for approval in suspended_state.deferred_tool_requests.approvals
        ],
    )
