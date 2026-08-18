# apps/api/route/classifiers/create_classifier.py

"""Route for creating a workspace classifier."""

from fastapi import APIRouter, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.classifiers import create_classifier as create_classifier_service
from services.classifiers.schemas import ClassifierCreateRequest, ClassifierRead

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_classifier(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: ClassifierCreateRequest,
) -> ClassifierRead:
    workspace, membership = workspace_context
    return await create_classifier_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
