# apps/api/routes/tools/list_presentations.py

"""Route for listing display metadata for every runtime tool."""

from fastapi import APIRouter

from core.dependencies import CurrentUserDep, CurrentWorkspaceDep
from services.agents.runtime.tools.registry import list_tool_presentations
from services.agents.runtime.tools.schemas import ToolPresentationEntry, ToolPresentationsResponse

router = APIRouter()


@router.get("/presentations")
async def list_tool_presentation_entries(
    _actor: CurrentUserDep,
    _workspace_context: CurrentWorkspaceDep,
) -> ToolPresentationsResponse:
    definitions = list_tool_presentations()
    return ToolPresentationsResponse(
        tools=[ToolPresentationEntry.from_definition(definition) for definition in definitions]
    )
