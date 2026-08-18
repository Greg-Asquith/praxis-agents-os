# apps/api/route/classifiers/update_classifier.py

"""Route for updating a workspace classifier."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.classifiers import update_classifier as update_classifier_service
from services.classifiers.schemas import ClassifierRead, ClassifierUpdateRequest

router = APIRouter()


@router.patch("/{classifier_id}")
async def update_classifier(
    request: Request,
    classifier_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: ClassifierUpdateRequest,
) -> ClassifierRead:
    workspace, membership = workspace_context
    return await update_classifier_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        classifier_id=classifier_id,
        payload=payload,
    )
