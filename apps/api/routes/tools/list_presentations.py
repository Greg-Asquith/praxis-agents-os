# apps/api/routes/tools/list_presentations.py

"""Route for listing display metadata for every runtime tool."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agents.runtime.tools.registry import list_tool_presentations
from services.agents.runtime.tools.schemas import ToolPresentationEntry, ToolPresentationsResponse
from services.agents.runtime.tools.workspace_tools import load_workspace_tool_definitions

router = APIRouter()


@router.get("/presentations")
async def list_tool_presentation_entries(
    _actor: CurrentUserDep,
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ToolPresentationsResponse:
    workspace, _membership = workspace_context
    workspace_definitions = await load_workspace_tool_definitions(db, workspace)
    definitions = list_tool_presentations(workspace_definitions)
    return ToolPresentationsResponse(
        tools=[ToolPresentationEntry.from_definition(definition) for definition in definitions]
    )
