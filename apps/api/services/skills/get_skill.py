# apps/api/services/skills/get_skill.py

"""Read a workspace-scoped skill."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.skills.schemas import SkillRead
from services.skills.utils import get_skill_for_workspace


async def get_skill(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_id: UUID,
) -> SkillRead:
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)
    return SkillRead.from_skill(skill)
