# apps/api/services/skills/delete_skill.py

"""Soft-delete a workspace or platform skill."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from models.skills import SkillScope
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.skills.platform_utils import (
    get_platform_skill,
    record_platform_skill_audit_event,
    require_platform_skill_admin,
)
from services.skills.utils import (
    get_visible_skill,
    require_skill_write_access,
)


async def delete_skill(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    skill_id: UUID,
) -> None:
    skill = await get_visible_skill(db, workspace=workspace, skill_id=skill_id)
    if skill.scope == SkillScope.PLATFORM:
        require_platform_skill_admin(actor)
        await db.commit()
        await _delete_platform_skill(
            request=request,
            actor=actor,
            skill_id=skill_id,
        )
        return

    require_skill_write_access(membership)

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


async def _delete_platform_skill(
    *,
    request: Request,
    actor: User,
    skill_id: UUID,
) -> None:
    """Soft-delete one platform skill through the maintenance role."""
    async with maintenance_async_db_session() as maintenance_db:
        skill = await get_platform_skill(
            maintenance_db,
            skill_id=skill_id,
            lock_for_update=True,
        )
        skill.soft_delete(deleted_by=actor.id, cascade=False)
        await maintenance_db.flush([skill])
        await record_platform_skill_audit_event(
            maintenance_db,
            request=request,
            actor=actor,
            action=AuditAction.DELETE,
            skill=skill,
            details={"skill_name": skill.name},
        )
