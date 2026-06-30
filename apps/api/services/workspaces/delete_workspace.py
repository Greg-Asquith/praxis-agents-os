# apps/api/services/workspaces/delete_workspace.py

"""Soft-delete a team workspace."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.workspaces.utils import (
    MANAGER_ROLES,
    get_workspace_or_raise,
    require_workspace_role,
)


async def delete_workspace(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
) -> None:
    workspace, _ = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    if workspace.is_personal:
        raise AppValidationError("Personal workspaces cannot be deleted", field="workspace_id")

    workspace = await get_workspace_or_raise(
        db,
        workspace_id=workspace_id,
        load_children=True,
    )
    workspace.soft_delete(deleted_by=actor.id, cascade=True)
    await db.execute(
        update(User)
        .where(User.default_workspace_id == workspace_id)
        .values(default_workspace_id=None)
    )
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.WORKSPACE,
        resource_id=workspace.id,
        actor=actor,
        details={"slug": workspace.slug},
    )
