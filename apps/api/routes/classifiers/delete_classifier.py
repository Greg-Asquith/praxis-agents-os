# apps/api/route/classifiers/delete_classifier.py

"""Route for deleting a workspace classifier."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.classifiers import delete_classifier as delete_classifier_service

router = APIRouter()


@router.delete("/{classifier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_classifier(
    request: Request,
    classifier_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> None:
    workspace, membership = workspace_context
    await delete_classifier_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        classifier_id=classifier_id,
    )
