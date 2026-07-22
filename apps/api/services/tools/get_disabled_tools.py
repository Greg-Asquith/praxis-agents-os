# apps/api/service/tools/get_disabled_tools.py

"""Read disabled runtime tools for one workspace."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from models.workspace_tool_settings import WorkspaceToolSetting
from services.tools.utils import cache_disabled_tools, get_cached_disabled_tools


async def get_disabled_tools(db: AsyncSession, workspace: Workspace) -> frozenset[str]:
    """Return disabled tool names, cached for the session's request scope."""
    cached = get_cached_disabled_tools(db, workspace.id)
    if cached is not None:
        return cached

    result = await db.execute(
        select(WorkspaceToolSetting.tool_name).where(
            WorkspaceToolSetting.workspace_id == workspace.id,
            WorkspaceToolSetting.enabled.is_(False),
        )
    )
    disabled = frozenset(result.scalars().all())
    cache_disabled_tools(db, workspace.id, disabled)
    return disabled
