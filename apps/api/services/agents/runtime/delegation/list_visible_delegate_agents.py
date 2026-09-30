# apps/api/services/agents/runtime/delegation/list_visible_delegate_agents.py

"""List delegate agents visible to the current caller."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.workspace import Workspace
from services.agents.runtime.delegation.constants import DELEGATE_LIST_LIMIT
from services.agents.runtime.delegation.utils import (
    load_caller_agent,
    normalized_allowed_agent_ids,
    visible_delegate_filters,
)


async def list_visible_delegate_agents(
    db: AsyncSession,
    *,
    caller: Agent,
    workspace: Workspace,
    search: str = "",
    agent_ids: Collection[UUID] | None = None,
    offset: int = 0,
    limit: int = DELEGATE_LIST_LIMIT,
) -> list[Agent]:
    """Return one page of visible delegate agents matching the optional search and IDs.

    Custom agents keep allowlist order; the built-in agent sees every other
    active agent in the workspace, by name.
    """
    fresh_caller = await load_caller_agent(db, caller=caller, workspace=workspace)
    filters = visible_delegate_filters(fresh_caller, workspace=workspace)
    if agent_ids is not None:
        filters.append(Agent.id.in_(list(agent_ids)))
    if pattern := _search_pattern(search):
        filters.append(
            or_(
                Agent.name.ilike(pattern, escape="\\"),
                Agent.description.ilike(pattern, escape="\\"),
            )
        )
    if fresh_caller.is_builtin:
        query = select(Agent).where(*filters).order_by(Agent.name, Agent.id)
        return list((await db.scalars(query.offset(offset).limit(limit))).all())

    # The allowlist is capped at 100, so ordering it in Python is bounded.
    agents = (await db.scalars(select(Agent).where(*filters))).all()
    agent_by_id = {agent.id: agent for agent in agents}
    allowed_ids = normalized_allowed_agent_ids(fresh_caller.allowed_agent_ids or [])
    ordered = [agent_by_id[agent_id] for agent_id in allowed_ids if agent_id in agent_by_id]
    return ordered[offset : offset + limit]


def _search_pattern(search: str) -> str | None:
    normalized = search.strip()
    if not normalized:
        return None
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
