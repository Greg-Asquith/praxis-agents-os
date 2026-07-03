# apps/api/routes/tools/list_catalog.py

"""Route for listing runtime tool catalog entries."""

from fastapi import APIRouter

from core.dependencies import CurrentUserDep, CurrentWorkspaceDep
from services.agents.runtime.tools.registry import list_allowed_tool_definitions
from services.agents.runtime.tools.schemas import ToolCatalogEntry, ToolCatalogResponse

router = APIRouter()


@router.get("/catalog")
async def list_tool_catalog(
    _actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ToolCatalogResponse:
    workspace, _membership = workspace_context
    definitions = list_allowed_tool_definitions(workspace=workspace)
    return ToolCatalogResponse(
        tools=[ToolCatalogEntry.from_definition(definition) for definition in definitions]
    )
