# apps/api/services/agents/runtime/delegation/list_visible_delegate_agents.py

"""List delegate agents visible to the current caller."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.workspace import Workspace
from services.agents.runtime.delegation.utils import (
    load_caller_agent,
    normalized_allowed_agent_ids,
)


async def list_visible_delegate_agents(
    db: AsyncSession,
    *,
    caller: Agent,
    workspace: Workspace,
) -> list[Agent]:
    """Return active same-workspace delegate agents in allowlist order."""
    fresh_caller = await load_caller_agent(db, caller=caller, workspace=workspace)
    allowed_ids = normalized_allowed_agent_ids(fresh_caller.allowed_agent_ids or [])
    if not allowed_ids:
        return []

    agents = (
        await db.scalars(
            select(Agent).where(
                Agent.id.in_(allowed_ids),
                Agent.workspace_id == workspace.id,
                Agent.deleted == False,  # noqa: E712
                Agent.is_active.is_(True),
                Agent.id != fresh_caller.id,
            )
        )
    ).all()
    agent_by_id = {agent.id: agent for agent in agents}
    return [agent_by_id[agent_id] for agent_id in allowed_ids if agent_id in agent_by_id]
