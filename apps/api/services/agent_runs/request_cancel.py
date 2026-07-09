# apps/api/services/agent_runs/request_cancel.py

"""Request cooperative cancellation for a workspace-scoped agent run."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError, NotFoundError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.cancel import cancel_agent_run
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, is_terminal
from services.agent_runs.schemas import AgentRunCancelResponse, AgentRunRead
from services.agent_runs.utils import load_delegated_child_run_for_approval
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.run_manager import run_task_registry
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.workspaces.utils import MANAGER_ROLES


async def request_agent_run_cancellation(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    run_id: UUID,
    request: Request | None = None,
) -> AgentRunCancelResponse:
    """Cancel a non-terminal run if the actor owns it or manages the workspace."""
    run = await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    if run is None:
        raise NotFoundError(
            "Agent run not found",
            resource_type="agent_run",
            resource_id=str(run_id),
        )

    if run.user_id != actor.id and membership.role not in MANAGER_ROLES:
        raise AuthorizationError(
            "Only the run owner or a workspace manager can cancel this agent run",
            details={
                "run_id": str(run.id),
                "run_user_id": str(run.user_id),
                "actor_user_id": str(actor.id),
                "membership_role": membership.role,
            },
        )

    if is_terminal(run.status):
        raise ConflictError(
            "Agent run is already terminal",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    previous_status = run.status
    cancelled_child_run_ids = await _cancel_delegated_child_approval_runs(db, parent_run=run)
    cancelled_run = await cancel_agent_run(db, run)
    await db.refresh(cancelled_run)
    run_read = AgentRunRead.from_run(cancelled_run)
    audit_details = {
        "operation": "cancel",
        "previous_status": previous_status,
        "status": cancelled_run.status,
        "run_user_id": str(cancelled_run.user_id),
        "conversation_id": str(cancelled_run.conversation_id),
    }
    if cancelled_child_run_ids:
        audit_details["cancelled_child_run_ids"] = [
            str(child_run_id) for child_run_id in cancelled_child_run_ids
        ]
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CANCEL,
        resource_type=AuditResourceType.AGENT_RUN,
        resource_id=cancelled_run.id,
        actor=actor,
        details=audit_details,
    )
    await db.commit()

    local_cancel_delivered = run_task_registry.cancel(cancelled_run.id)
    for child_run_id in cancelled_child_run_ids:
        run_task_registry.cancel(child_run_id)
    return AgentRunCancelResponse(
        run=run_read,
        local_cancel_delivered=local_cancel_delivered,
    )


async def _cancel_delegated_child_approval_runs(
    db: AsyncSession,
    *,
    parent_run: AgentRun,
) -> list[UUID]:
    if parent_run.status != RUN_STATUS_AWAITING_APPROVAL:
        return []

    try:
        suspended_state = load_suspended_run_state(parent_run)
    except ConflictError:
        return []

    cancelled_child_run_ids: list[UUID] = []
    seen_child_run_ids: set[UUID] = set()
    for metadata in suspended_state.deferred_tool_requests.metadata.values():
        child_run = await load_delegated_child_run_for_approval(
            db,
            parent_run=parent_run,
            metadata=metadata,
            lock=True,
        )
        if child_run is None or child_run.id in seen_child_run_ids:
            continue

        await cancel_agent_run(db, child_run)
        cancelled_child_run_ids.append(child_run.id)
        seen_child_run_ids.add(child_run.id)

    return cancelled_child_run_ids
