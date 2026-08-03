# apps/api/services/tools/utils.py

"""Request-scoped cache helpers for tool availability services."""

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

_DISABLED_TOOLS_CACHE_KEY: Final = "workspace_disabled_tools"


def get_cached_disabled_tools(
    db: AsyncSession,
    workspace_id: UUID,
) -> frozenset[str] | None:
    return db.info.setdefault(_DISABLED_TOOLS_CACHE_KEY, {}).get(workspace_id)


def cache_disabled_tools(
    db: AsyncSession,
    workspace_id: UUID,
    disabled_tool_names: frozenset[str],
) -> None:
    db.info.setdefault(_DISABLED_TOOLS_CACHE_KEY, {})[workspace_id] = disabled_tool_names


def invalidate_disabled_tools_cache(db: AsyncSession, workspace_id: UUID) -> None:
    db.info.get(_DISABLED_TOOLS_CACHE_KEY, {}).pop(workspace_id, None)
