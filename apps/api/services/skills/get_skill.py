# apps/api/services/skills/get_skill.py

"""Read a skill visible in a workspace."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.skills.schemas import SkillRead
from services.skills.utils import get_visible_skill


async def get_skill(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_id: UUID,
) -> SkillRead:
    skill = await get_visible_skill(db, workspace=workspace, skill_id=skill_id)
    return SkillRead.from_skill(skill)
