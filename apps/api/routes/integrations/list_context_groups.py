# apps/api/routes/integrations/list_context_groups.py

"""List integration context groups in the current workspace."""

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep, require_read
from services.integrations.context import list_context_groups as list_context_groups_service
from services.integrations.context.schemas import ContextGroupListResponse

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/context-groups")
async def list_context_groups(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ContextGroupListResponse:
    workspace, _membership = workspace_context
    return await list_context_groups_service(db, workspace=workspace)
