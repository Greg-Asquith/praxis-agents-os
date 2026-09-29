# apps/api/services/tools/get_workspace_tool_defaults.py

"""Read disabled tools and default approval policies for one workspace."""

from types import MappingProxyType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from models.workspace_tool_settings import WorkspaceToolSetting
from services.tools.domain import WorkspaceToolDefaults
from services.tools.utils import cache_tool_defaults, get_cached_tool_defaults


async def get_workspace_tool_defaults(
    db: AsyncSession,
    workspace: Workspace,
) -> WorkspaceToolDefaults:
    """Return workspace tool defaults, cached for the session's request scope."""
    cached = get_cached_tool_defaults(db, workspace.id)
    if cached is not None:
        return cached

    rows = (
        await db.execute(
            select(
                WorkspaceToolSetting.tool_name,
                WorkspaceToolSetting.enabled,
                WorkspaceToolSetting.policy,
            ).where(WorkspaceToolSetting.workspace_id == workspace.id)
        )
    ).all()
    defaults = WorkspaceToolDefaults(
        disabled=frozenset(name for name, enabled, _policy in rows if not enabled),
        policies=MappingProxyType(
            {name: policy for name, _enabled, policy in rows if policy is not None}
        ),
    )
    cache_tool_defaults(db, workspace.id, defaults)
    return defaults
