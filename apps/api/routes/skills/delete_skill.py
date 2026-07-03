# apps/api/routes/skills/delete_skill.py

"""Route for soft-deleting a workspace skill."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.skills import delete_skill as delete_skill_service

router = APIRouter()


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
) -> None:
    workspace, membership = workspace_context
    await delete_skill_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        skill_id=skill_id,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
