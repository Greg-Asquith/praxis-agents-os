# apps/api/routes/email_suppressions/remove_email_suppression.py

"""Route for removing an address from the Do Not Email list."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_owner,
)
from services.email_suppressions import remove_email_suppression as remove_service

# A removal lets agents email someone again, so only owners and admins can make it.
router = APIRouter(dependencies=[Depends(require_owner)])


@router.delete("/{suppression_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_email_suppression(
    request: Request,
    suppression_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> None:
    workspace, _membership = workspace_context
    await remove_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        suppression_id=suppression_id,
    )
