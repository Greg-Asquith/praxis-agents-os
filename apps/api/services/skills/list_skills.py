# apps/api/services/skills/list_skills.py

"""List skills visible in a workspace."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.skills import Skill
from models.workspace import Workspace
from services.skills.schemas import SkillRead, SkillsListResponse
from utils.pagination import paginate


async def list_skills(
    db: AsyncSession,
    *,
    workspace: Workspace,
    limit: int,
    offset: int,
    include_inactive: bool,
) -> SkillsListResponse:
    filters = [
        Skill.workspace_id == workspace.id,
        Skill.deleted == False,  # noqa: E712
    ]
    if not include_inactive:
        filters.append(Skill.is_active.is_(True))

    skills, total = await paginate(
        db,
        select(Skill).where(*filters),
        Skill.created_at.desc(),
        limit=limit,
        offset=offset,
    )

    return SkillsListResponse(
        skills=[SkillRead.from_skill(skill) for skill in skills],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
