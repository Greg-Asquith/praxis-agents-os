# apps/api/services/skills/list_skills.py

"""List skills visible in a workspace."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.skills import Skill
from models.user import User
from models.workspace import Workspace
from services.skills.schemas import SkillRead, SkillsListResponse
from services.skills.utils import visible_skill_filter
from utils.pagination import paginate
from utils.search import contains_pattern


async def list_skills(
    db: AsyncSession,
    *,
    workspace: Workspace,
    limit: int,
    offset: int,
    include_inactive: bool,
    actor: User | None = None,
    search: str | None = None,
) -> SkillsListResponse:
    filters = [
        visible_skill_filter(workspace),
        Skill.deleted == False,  # noqa: E712
    ]
    if not include_inactive:
        filters.append(Skill.is_active.is_(True))
    if search:
        pattern = contains_pattern(search)
        filters.append(
            or_(
                Skill.name.ilike(pattern, escape="\\"),
                Skill.human_name.ilike(pattern, escape="\\"),
                Skill.description.ilike(pattern, escape="\\"),
            )
        )

    skills, total = await paginate(
        db,
        select(Skill).where(*filters),
        Skill.created_at.desc(),
        limit=limit,
        offset=offset,
    )

    return SkillsListResponse(
        skills=[SkillRead.from_skill(skill, actor=actor) for skill in skills],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
