# apps/api/services/skills/create_skill.py

"""Create a workspace or platform skill."""

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.general import AppValidationError
from models.skills import Skill, SkillScope
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.skills.platform_utils import (
    record_platform_skill_audit_event,
    require_platform_skill_admin,
)
from services.skills.schemas import SkillCreateRequest, SkillRead
from services.skills.utils import classify_skill_integrity_error, require_skill_write_access


async def create_skill(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: SkillCreateRequest,
) -> SkillRead:
    if payload.scope == SkillScope.PLATFORM:
        require_platform_skill_admin(actor)
        if payload.is_favorite:
            raise AppValidationError(
                "Platform skills cannot be marked as favorites",
                field="is_favorite",
            )
        await db.commit()
        return await _create_platform_skill(request=request, actor=actor, payload=payload)

    require_skill_write_access(membership)

    skill = Skill(
        name=payload.name,
        human_name=payload.human_name,
        description=payload.description,
        instructions=payload.instructions,
        workspace_id=workspace.id,
        created_by=actor.id,
        scope=SkillScope.WORKSPACE,
        is_active=payload.is_active,
        is_favorite=payload.is_favorite,
        metadata_json=payload.metadata_json,
    )
    try:
        async with db.begin_nested():
            db.add(skill)
            await db.flush([skill])
    except IntegrityError as exc:
        if skill in db:
            db.expunge(skill)
        conflict = classify_skill_integrity_error(exc)
        if conflict is not None:
            raise conflict from exc
        raise

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.SKILL,
        resource_id=skill.id,
        actor=actor,
        details={"skill_name": skill.name},
    )
    await db.refresh(skill)
    return SkillRead.from_skill(skill)


async def _create_platform_skill(
    *,
    request: Request,
    actor: User,
    payload: SkillCreateRequest,
) -> SkillRead:
    """Create one platform skill through the maintenance role."""
    skill = Skill(
        name=payload.name,
        human_name=payload.human_name,
        description=payload.description,
        instructions=payload.instructions,
        scope=SkillScope.PLATFORM,
        workspace_id=None,
        created_by=actor.id,
        documentation_refs={},
        is_active=payload.is_active,
        is_favorite=False,
        metadata_json=payload.metadata_json,
    )
    async with maintenance_async_db_session() as maintenance_db:
        try:
            async with maintenance_db.begin_nested():
                maintenance_db.add(skill)
                await maintenance_db.flush([skill])
        except IntegrityError as exc:
            conflict = classify_skill_integrity_error(exc)
            if conflict is not None:
                raise conflict from exc
            raise
        await record_platform_skill_audit_event(
            maintenance_db,
            request=request,
            actor=actor,
            action=AuditAction.CREATE,
            skill=skill,
            details={"skill_name": skill.name},
        )
        await maintenance_db.refresh(skill)
        return SkillRead.from_skill(skill)
