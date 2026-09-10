# apps/api/services/skills/update_skill.py

"""Update a workspace or platform skill."""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.dependencies import require_super_admin_user
from core.exceptions.general import AppValidationError
from models.skills import Skill
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.skills.platform_utils import (
    get_platform_skill,
    record_platform_skill_audit_event,
)
from services.skills.schemas import SkillRead, SkillUpdateRequest
from services.skills.utils import (
    classify_skill_integrity_error,
    get_visible_skill,
    require_skill_write_access,
)
from utils.content import ContentScope


async def update_skill(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    skill_id: UUID,
    payload: SkillUpdateRequest,
) -> SkillRead:
    skill = await get_visible_skill(db, workspace=workspace, skill_id=skill_id)
    if skill.scope == ContentScope.PLATFORM:
        require_super_admin_user(actor)
        await db.commit()
        return await _update_platform_skill(
            request=request,
            actor=actor,
            skill_id=skill_id,
            payload=payload,
        )

    require_skill_write_access(membership)

    changed_fields: list[str] = []

    for required_field in ("name", "description", "instructions"):
        if required_field in payload.model_fields_set and getattr(payload, required_field) is None:
            raise AppValidationError(
                f"{required_field} cannot be null",
                field=required_field,
            )

    for field_name in (
        "name",
        "human_name",
        "description",
        "instructions",
        "is_active",
        "is_favorite",
        "metadata_json",
    ):
        if field_name in payload.model_fields_set:
            _set_if_changed(skill, field_name, getattr(payload, field_name), changed_fields)

    if changed_fields:
        try:
            await db.flush()
        except IntegrityError as exc:
            conflict = classify_skill_integrity_error(exc)
            if conflict is not None:
                raise conflict from exc
            raise
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.SKILL,
            resource_id=skill.id,
            actor=actor,
            details={"changed_fields": changed_fields},
        )
        await db.refresh(skill)

    return SkillRead.from_skill(skill, actor=actor)


def _set_if_changed(skill: Skill, field_name: str, value: Any, changed_fields: list[str]) -> None:
    if getattr(skill, field_name) != value:
        setattr(skill, field_name, value)
        changed_fields.append(field_name)


async def _update_platform_skill(
    *,
    request: Request,
    actor: User,
    skill_id: UUID,
    payload: SkillUpdateRequest,
) -> SkillRead:
    """Update one platform skill through the maintenance role."""
    if payload.is_favorite is True:
        raise AppValidationError(
            "Platform skills cannot be marked as favorites",
            field="is_favorite",
        )
    for required_field in ("name", "description", "instructions"):
        if required_field in payload.model_fields_set and getattr(payload, required_field) is None:
            raise AppValidationError(f"{required_field} cannot be null", field=required_field)

    async with maintenance_async_db_session() as maintenance_db:
        skill = await get_platform_skill(
            maintenance_db,
            skill_id=skill_id,
            lock_for_update=True,
        )
        changed_fields: list[str] = []
        for field_name in (
            "name",
            "human_name",
            "description",
            "instructions",
            "is_active",
            "metadata_json",
        ):
            if field_name in payload.model_fields_set:
                _set_if_changed(skill, field_name, getattr(payload, field_name), changed_fields)
        if changed_fields:
            try:
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
                action=AuditAction.UPDATE,
                skill=skill,
                details={"changed_fields": changed_fields},
            )
        await maintenance_db.refresh(skill)
        return SkillRead.from_skill(skill, actor=actor)
