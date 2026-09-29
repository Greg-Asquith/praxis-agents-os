# apps/api/services/tools/list_tool_settings.py

"""List every configurable tool with its workspace settings."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.agents.runtime.tools.registry import list_allowed_tool_definitions
from services.tools.get_workspace_tool_defaults import get_workspace_tool_defaults
from services.tools.schemas import ToolSettingRead, ToolSettingsResponse


async def list_tool_settings(db: AsyncSession, workspace: Workspace) -> ToolSettingsResponse:
    """Return configurable static tools, including disabled ones, with their settings."""
    defaults = await get_workspace_tool_defaults(db, workspace)
    return ToolSettingsResponse(
        tools=[
            ToolSettingRead(
                name=definition.name,
                provider=definition.provider,
                label=definition.label,
                description=definition.description,
                effect=definition.effect,
                default_policy=definition.default_policy,
                supported_policies=sorted(definition.allowed_policies()),
                enabled=definition.name not in defaults.disabled,
                policy=defaults.policies.get(definition.name),
            )
            for definition in list_allowed_tool_definitions(workspace=workspace)
        ]
    )
