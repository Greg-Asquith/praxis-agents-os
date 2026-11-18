# apps/api/routes/email_suppressions/add_email_suppressions.py

"""Route for adding pasted addresses to the Do Not Email list."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.email_suppressions import add_email_suppressions as add_service
from services.email_suppressions.schemas import (
    EmailSuppressionAddRequest,
    EmailSuppressionAddResponse,
)

router = APIRouter()


@router.post("/")
async def add_email_suppressions(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: EmailSuppressionAddRequest,
) -> EmailSuppressionAddResponse:
    workspace, _membership = workspace_context
    return await add_service(db, request=request, actor=actor, workspace=workspace, payload=payload)
