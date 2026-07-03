# apps/api/routes/skills/update_skill.py

"""Route for updating a workspace skill."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.skills import update_skill as update_skill_service
from services.skills.schemas import SkillRead, SkillUpdateRequest

router = APIRouter()


@router.patch("/{skill_id}")
async def update_skill(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
    payload: SkillUpdateRequest,
) -> SkillRead:
    workspace, membership = workspace_context
    return await update_skill_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        skill_id=skill_id,
        payload=payload,
    )
