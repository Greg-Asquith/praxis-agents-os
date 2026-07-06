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
    PendingDelegatedApprovalRead,
    PendingToolApprovalRead,
)
from services.agent_runs.utils import load_delegated_child_run_for_approval
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY,
)
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.staged_tool_content import tool_args_for_display
from utils.metadata import metadata_str


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
    approvals: list[PendingToolApprovalRead] = []
    delegations: list[PendingDelegatedApprovalRead] = []
    for approval in suspended_state.deferred_tool_requests.approvals:
        metadata = suspended_state.deferred_tool_requests.metadata.get(approval.tool_call_id)
        child_run = await load_delegated_child_run_for_approval(
            db,
            parent_run=run,
            metadata=metadata,
        )
        if child_run is None:
            approvals.append(
                PendingToolApprovalRead(
                    tool_call_id=approval.tool_call_id,
                    name=approval.tool_name,
                    args=to_jsonable_python(
                        tool_args_for_display(
                            tool_name=approval.tool_name,
                            args=approval.args,
                            metadata=metadata,
                        )
                    ),
                )
            )
            continue

        child_state = load_suspended_run_state(child_run)
        delegation = PendingDelegatedApprovalRead(
            parent_tool_call_id=approval.tool_call_id,
            child_agent_id=child_run.agent_id,
            child_agent_name=metadata_str(metadata.get(DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY))
            or "Delegate agent",
            child_conversation_id=child_run.conversation_id,
            child_run_id=child_run.id,
            pending_approval_count=len(child_state.pending_tool_call_ids),
        )
        delegations.append(delegation)
        approvals.extend(
            PendingToolApprovalRead(
                tool_call_id=child_approval.tool_call_id,
                name=child_approval.tool_name,
                args=to_jsonable_python(
                    tool_args_for_display(
                        tool_name=child_approval.tool_name,
                        args=child_approval.args,
                        metadata=child_state.deferred_tool_requests.metadata.get(
                            child_approval.tool_call_id
                        ),
                    )
                ),
                delegation=delegation,
            )
            for child_approval in child_state.deferred_tool_requests.approvals
        )

    return AgentRunApprovalStateResponse(
        run_id=run.id,
        conversation_id=run.conversation_id,
        approvals=approvals,
        delegations=delegations,
    )
