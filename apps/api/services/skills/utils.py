# apps/api/services/skills/utils.py

"""Helpers specific to workspace skill services."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError, NotFoundError
from models.skills import Skill
from models.workspace import Workspace, WorkspaceMembership
from services.workspaces.utils import EDITOR_ROLES

SKILL_NAME_UNIQUE_CONSTRAINT = "uq_skills_workspace_name"


async def get_skill_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_id: UUID,
) -> Skill:
    skill = await db.scalar(
        select(Skill).where(
            Skill.id == skill_id,
            Skill.workspace_id == workspace.id,
            Skill.deleted == False,  # noqa: E712
        )
    )
    if skill is None:
        raise NotFoundError(
            "Skill not found",
            resource_type="skill",
            resource_id=str(skill_id),
        )
    return skill


def require_skill_write_access(membership: WorkspaceMembership) -> None:
    if membership.role not in EDITOR_ROLES:
        raise AuthorizationError(
            "Requires workspace write access",
            details={
                "allowed_roles": sorted(EDITOR_ROLES),
                "membership_id": str(membership.id),
                "membership_role": membership.role,
                "workspace_id": str(membership.workspace_id),
                "user_id": str(membership.user_id),
            },
        )


def classify_skill_integrity_error(exc: IntegrityError) -> ConflictError | None:
    constraint_names = _integrity_constraint_names(exc)
    if SKILL_NAME_UNIQUE_CONSTRAINT in constraint_names or SKILL_NAME_UNIQUE_CONSTRAINT in str(exc):
        return ConflictError(
            "A skill with this name already exists in the workspace",
            conflicting_resource="skill",
        )
    return None


def _integrity_constraint_names(exc: IntegrityError) -> set[str]:
    names: set[str] = set()
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    for attr in ("constraint_name", "table_name"):
        value = getattr(diag, attr, None)
        if value:
            names.add(str(value))
    return names
