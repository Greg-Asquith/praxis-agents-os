# apps/api/routes/tools/list_settings.py

"""List workspace tool settings for workspace managers."""

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep, require_owner
from services.tools import list_tool_settings
from services.tools.schemas import ToolSettingsResponse

router = APIRouter(dependencies=[Depends(require_owner)])


@router.get("/settings")
async def list_workspace_tool_settings(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ToolSettingsResponse:
    workspace, _membership = workspace_context
    return await list_tool_settings(db, workspace)
