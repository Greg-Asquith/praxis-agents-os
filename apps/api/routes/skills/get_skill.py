# apps/api/routes/skills/get_skill.py

"""Route for reading a workspace skill."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.skills import get_skill as get_skill_service
from services.skills.schemas import SkillRead

router = APIRouter()


@router.get("/{skill_id}")
async def get_skill(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
) -> SkillRead:
    workspace, _membership = workspace_context
    return await get_skill_service(db, workspace=workspace, skill_id=skill_id)
