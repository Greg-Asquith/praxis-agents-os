# apps/api/routes/schedules/preview_schedule.py

"""Route for previewing schedule fire times."""

from fastapi import APIRouter

from core.dependencies import CurrentWorkspaceDep
from services.agent_schedules import preview_schedule as preview_schedule_service
from services.agent_schedules.schemas import SchedulePreviewRequest, SchedulePreviewResponse

router = APIRouter()


@router.post("/preview")
async def preview_schedule(
    workspace_context: CurrentWorkspaceDep,
    payload: SchedulePreviewRequest,
) -> SchedulePreviewResponse:
    _workspace, _membership = workspace_context
    return await preview_schedule_service(payload)
