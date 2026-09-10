# apps/api/services/skills/platform_utils.py

"""Helpers for super-admin-managed platform skills."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.skills import Skill
from models.user import User
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)
from utils.content import ContentScope


async def get_platform_skill(
    db: AsyncSession,
    *,
    skill_id: UUID,
    lock_for_update: bool = False,
) -> Skill:
    statement = select(Skill).where(
        Skill.id == skill_id,
        Skill.scope == ContentScope.PLATFORM,
        Skill.deleted == False,  # noqa: E712
    )
    if lock_for_update:
        statement = statement.with_for_update(of=Skill)
    skill = await db.scalar(statement)
    if skill is None:
        raise NotFoundError(
            "Skill not found",
            resource_type="skill",
            resource_id=str(skill_id),
        )
    return skill


async def record_platform_skill_audit_event(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    action: AuditAction,
    skill: Skill,
    details: dict[str, object],
) -> None:
    """Record a platform-wide skill mutation without a workspace owner."""
    await safe_record_operation_audit_event(
        db,
        workspace_id=None,
        action=action,
        resource_type=AuditResourceType.SKILL,
        resource_id=skill.id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        actor_display=actor.email,
        requested_by_user_id=actor.id,
        details={"scope": ContentScope.PLATFORM.value, **details},
        request=request,
    )
