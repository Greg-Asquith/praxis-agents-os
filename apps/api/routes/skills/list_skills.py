# apps/api/routes/skills/list_skills.py

"""Route for listing workspace skills."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.skills import list_skills as list_skills_service
from services.skills.schemas import SkillsListResponse

router = APIRouter()


@router.get("/")
async def list_skills(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_inactive: bool = False,
) -> SkillsListResponse:
    workspace, _membership = workspace_context
    return await list_skills_service(
        db,
        workspace=workspace,
        limit=limit,
        offset=offset,
        include_inactive=include_inactive,
    )
