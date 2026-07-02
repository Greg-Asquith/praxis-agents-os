# apps/api/services/agents/runtime/delegation/list_delegate_agents.py

"""Model-facing tool for listing visible delegate agents."""

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.list_visible_delegate_agents import (
    list_visible_delegate_agents,
)
from services.agents.runtime.delegation.schemas import DelegateAgentSummary
from services.agents.runtime.delegation.summary import summarize_delegate_agent


async def list_delegate_agents(ctx: RunContext[RuntimeDeps]) -> list[DelegateAgentSummary]:
    """List delegate agents visible to the current runtime agent."""
    delegates = await list_visible_delegate_agents(
        ctx.deps.db,
        caller=ctx.deps.agent,
        workspace=ctx.deps.workspace,
    )
    return [summarize_delegate_agent(agent) for agent in delegates]
