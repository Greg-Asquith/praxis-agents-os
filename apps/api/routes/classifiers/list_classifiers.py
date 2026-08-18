# apps/api/route/classifiers/list_classifier.py

"""Route for listing workspace classifiers."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.classifiers import list_classifiers as list_classifiers_service
from services.classifiers.schemas import ClassifiersListResponse

router = APIRouter()


@router.get("/")
async def list_classifiers(
    _actor: CurrentUserDep,
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_inactive: bool = True,
) -> ClassifiersListResponse:
    workspace, _membership = workspace_context
    return await list_classifiers_service(
        db,
        workspace=workspace,
        limit=limit,
        offset=offset,
        include_inactive=include_inactive,
    )
