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
from services.agent_runs.domain import RUN_STATUS_CANCELLED, is_terminal
from services.agent_runs.schemas import AgentRunCancelResponse, AgentRunRead
from services.agent_runs.settle_run_family import lock_run_family, settle_run_family
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
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.deleted == False,  # noqa: E712
        )
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

    await lock_run_family(db, run_id=run_id)
    if is_terminal(run.status):
        raise ConflictError(
            "Agent run is already terminal",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    previous_status = run.status
    changed = await settle_run_family(db, run_id=run_id, status=RUN_STATUS_CANCELLED)
    cancelled_child_run_ids = [child.id for child in changed if child.id != run_id]
    cancelled_run = run
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
