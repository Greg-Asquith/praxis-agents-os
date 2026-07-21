# apps/api/services/integrations/context/delete_context_group.py

"""Soft-delete a workspace integration context group."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.integrations.context.utils import load_workspace_group


async def delete_context_group(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    group_id: UUID,
) -> None:
    """Soft-delete a group without chasing selections or schedule references.

    Those references deliberately become dangling context and are degraded by
    runtime resolution instead of making group deletion unsafe.
    """
    group = await load_workspace_group(db, group_id=group_id, workspace=workspace)
    group.soft_delete(deleted_by=actor.id, cascade=False)
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.INTEGRATION_CONTEXT_GROUP,
        resource_id=group.id,
        actor=actor,
        details={"name": group.name},
    )
