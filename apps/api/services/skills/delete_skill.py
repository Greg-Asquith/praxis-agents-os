# apps/api/services/skills/delete_skill.py

"""Soft-delete a workspace-scoped skill."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.skills.utils import get_skill_for_workspace, require_skill_write_access


async def delete_skill(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    skill_id: UUID,
) -> None:
    require_skill_write_access(membership)
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)

    skill.soft_delete(deleted_by=actor.id, cascade=False)
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.SKILL,
        resource_id=skill.id,
        actor=actor,
        details={"skill_name": skill.name},
    )
