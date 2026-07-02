# apps/api/services/agents/runtime/delegation/get_visible_delegate_agent.py

"""Load one delegate agent visible to the current caller."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.workspace import Workspace
from services.agents.runtime.delegation.utils import (
    load_caller_agent,
    normalized_allowed_agent_ids,
)


async def get_visible_delegate_agent(
    db: AsyncSession,
    *,
    caller: Agent,
    workspace: Workspace,
    target_agent_id: UUID,
) -> Agent:
    """Load one visible delegate agent, re-checking the allowlist at execution time."""
    fresh_caller = await load_caller_agent(db, caller=caller, workspace=workspace)
    allowed_ids = set(normalized_allowed_agent_ids(fresh_caller.allowed_agent_ids or []))
    if target_agent_id not in allowed_ids or target_agent_id == fresh_caller.id:
        raise NotFoundError(
            "Delegate agent not found",
            resource_type="agent",
            resource_id=str(target_agent_id),
        )

    target = await db.scalar(
        select(Agent).where(
            Agent.id == target_agent_id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
            Agent.is_active.is_(True),
        )
    )
    if target is None:
        raise NotFoundError(
            "Delegate agent not found",
            resource_type="agent",
            resource_id=str(target_agent_id),
        )
    return target
