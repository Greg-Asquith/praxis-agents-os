# apps/api/routes/status/get_summary.py

"""Route for an exact workspace status summary."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.status import get_status_summary as get_status_summary_service
from services.status.schemas import StatusSummary

router = APIRouter()


@router.get("/summary")
async def get_status_summary(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> StatusSummary:
    workspace, _membership = workspace_context
    return await get_status_summary_service(db, actor=actor, workspace=workspace)
