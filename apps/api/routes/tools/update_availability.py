# apps/api/routes/tools/update_availability.py

"""Change static tool availability; workspace-defined tools use their own lifecycle routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_owner
from services.tools import set_tool_enabled
from services.tools.schemas import ToolAvailabilityRead, ToolAvailabilityUpdateRequest

router = APIRouter(dependencies=[Depends(require_owner)])


@router.put("/{tool_name}/availability")
async def update_tool_availability(
    request: Request,
    payload: ToolAvailabilityUpdateRequest,
    tool_name: Annotated[str, Path(min_length=1, max_length=100)],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ToolAvailabilityRead:
    workspace, _membership = workspace_context
    return await set_tool_enabled(
        db,
        workspace=workspace,
        tool_name=tool_name,
        enabled=payload.enabled,
        actor=actor,
        request=request,
    )
