# apps/api/route/classifiers/get_classifier.py

"""Route for reading a workspace classifier."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.classifiers import get_classifier as get_classifier_service
from services.classifiers.schemas import ClassifierRead

router = APIRouter()


@router.get("/{classifier_id}")
async def get_classifier(
    classifier_id: Annotated[UUID, Path()],
    _actor: CurrentUserDep,
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ClassifierRead:
    workspace, _membership = workspace_context
    return await get_classifier_service(db, workspace=workspace, classifier_id=classifier_id)
