# apps/api/services/tools/utils.py

"""Helpers shared by workspace tool setting services."""

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.tools.domain import WorkspaceToolDefaults

_TOOL_DEFAULTS_CACHE_KEY: Final = "workspace_tool_defaults"


def get_cached_tool_defaults(
    db: AsyncSession,
    workspace_id: UUID,
) -> WorkspaceToolDefaults | None:
    return db.info.setdefault(_TOOL_DEFAULTS_CACHE_KEY, {}).get(workspace_id)


def cache_tool_defaults(
    db: AsyncSession,
    workspace_id: UUID,
    defaults: WorkspaceToolDefaults,
) -> None:
    db.info.setdefault(_TOOL_DEFAULTS_CACHE_KEY, {})[workspace_id] = defaults


def invalidate_tool_defaults_cache(db: AsyncSession, workspace_id: UUID) -> None:
    db.info.get(_TOOL_DEFAULTS_CACHE_KEY, {}).pop(workspace_id, None)


def require_configurable_tool(tool_name: str) -> RuntimeToolDefinition:
    """Return a configurable static catalog tool or raise not found."""
    definition = RUNTIME_TOOL_CATALOG.get(tool_name)
    if definition is None or not definition.configurable:
        raise NotFoundError(
            "Runtime tool not found",
            resource_type="tool",
            resource_id=tool_name,
        )
    return definition
