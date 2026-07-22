# apps/api/routes/tools/list_catalog.py

"""Route for listing runtime tool catalog entries."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agents.runtime.tools.registry import list_allowed_tool_definitions
from services.agents.runtime.tools.schemas import ToolCatalogEntry, ToolCatalogResponse
from services.tools import get_disabled_tools

router = APIRouter()


@router.get("/catalog")
async def list_tool_catalog(
    _actor: CurrentUserDep,
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ToolCatalogResponse:
    workspace, _membership = workspace_context
    disabled_tool_names = await get_disabled_tools(db, workspace)
    definitions = list_allowed_tool_definitions(
        workspace=workspace,
        disabled_tool_names=disabled_tool_names,
    )
    return ToolCatalogResponse(
        tools=[ToolCatalogEntry.from_definition(definition) for definition in definitions]
    )
