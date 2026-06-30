# apps/api/services/agents/delete_agent.py

"""Soft-delete a workspace-scoped agent."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agents.utils import get_agent_for_workspace, require_agent_write_access
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def delete_agent(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    agent_id: UUID,
) -> None:
    require_agent_write_access(membership)
    agent = await get_agent_for_workspace(db, workspace=workspace, agent_id=agent_id)

    agent.soft_delete(deleted_by=actor.id, cascade=False)
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.AGENT,
        resource_id=agent.id,
        actor=actor,
        details={"slug": agent.slug},
    )
