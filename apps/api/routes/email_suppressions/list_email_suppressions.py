# apps/api/routes/email_suppressions/list_email_suppressions.py

"""Route for listing the workspace Do Not Email list."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.email_suppressions import list_email_suppressions as list_service
from services.email_suppressions.schemas import EmailSuppressionListResponse

router = APIRouter()


@router.get("/")
async def list_email_suppressions(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    search: Annotated[str | None, Query(max_length=320)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EmailSuppressionListResponse:
    workspace, _membership = workspace_context
    return await list_service(db, workspace=workspace, search=search, limit=limit, offset=offset)
