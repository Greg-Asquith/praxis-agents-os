# apps/api/routes/tools/list_catalog.py

"""Route for listing runtime tool catalog entries."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agents.runtime.tools.registry import list_allowed_tool_definitions
from services.agents.runtime.tools.schemas import ToolCatalogEntry, ToolCatalogResponse
from services.agents.runtime.tools.workspace_tools import load_workspace_tool_definitions
from services.tools import get_workspace_tool_defaults

router = APIRouter()


@router.get("/catalog")
async def list_tool_catalog(
    _actor: CurrentUserDep,
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ToolCatalogResponse:
    workspace, _membership = workspace_context
    tool_defaults = await get_workspace_tool_defaults(db, workspace)
    workspace_definitions = await load_workspace_tool_definitions(db, workspace)
    definitions = list_allowed_tool_definitions(
        workspace=workspace,
        disabled_tool_names=tool_defaults.disabled,
        workspace_definitions=workspace_definitions,
    )
    return ToolCatalogResponse(
        tools=[
            ToolCatalogEntry.from_definition(
                definition,
                workspace_policy=tool_defaults.policies.get(definition.name),
            )
            for definition in definitions
        ]
    )
