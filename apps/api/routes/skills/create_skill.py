# apps/api/routes/skills/create_skill.py

"""Route for creating a workspace skill."""

from fastapi import APIRouter, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.skills import create_skill as create_skill_service
from services.skills.schemas import SkillCreateRequest, SkillRead

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: SkillCreateRequest,
) -> SkillRead:
    workspace, membership = workspace_context
    return await create_skill_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
