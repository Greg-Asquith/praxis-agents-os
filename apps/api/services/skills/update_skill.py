# apps/api/services/skills/update_skill.py

"""Update a workspace-scoped skill."""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.skills import Skill
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.skills.schemas import SkillRead, SkillUpdateRequest
from services.skills.utils import (
    classify_skill_integrity_error,
    get_skill_for_workspace,
    require_skill_write_access,
)


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
    require_skill_write_access(membership)
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)

    changed_fields: list[str] = []

    for required_field in ("name", "description", "instructions"):
        if (
            required_field in payload.model_fields_set
            and getattr(payload, required_field) is None
        ):
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

    return SkillRead.from_skill(skill)


def _set_if_changed(skill: Skill, field_name: str, value: Any, changed_fields: list[str]) -> None:
    if getattr(skill, field_name) != value:
        setattr(skill, field_name, value)
        changed_fields.append(field_name)
