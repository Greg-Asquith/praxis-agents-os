# apps/api/services/skills/create_skill.py

"""Create a workspace-scoped skill."""

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.skills import Skill
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
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
    require_skill_write_access(membership)

    skill = Skill(
        name=payload.name,
        human_name=payload.human_name,
        description=payload.description,
        instructions=payload.instructions,
        workspace_id=workspace.id,
        created_by=actor.id,
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
