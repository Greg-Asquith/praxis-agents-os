# apps/api/services/agents/runtime/delegation/list_delegate_agents.py

"""Model-facing tool for listing visible delegate agents."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.list_visible_delegate_agents import (
    list_visible_delegate_agents,
)
from services.agents.runtime.delegation.schemas import DelegateAgentSummary
from services.agents.runtime.delegation.summary import summarize_delegate_agent


async def list_delegate_agents(
    ctx: RunContext[RuntimeDeps],
    search: Annotated[
        str,
        Field(description="Optional words from an agent's name or description.", max_length=200),
    ] = "",
) -> list[DelegateAgentSummary]:
    """List delegate agents visible to the current runtime agent."""
    delegates = await list_visible_delegate_agents(
        ctx.deps.db,
        caller=ctx.deps.agent,
        workspace=ctx.deps.workspace,
        search=search,
    )
    return [
        summarize_delegate_agent(
            agent,
            workspace=ctx.deps.workspace,
            workspace_definitions=ctx.deps.workspace_tool_definitions,
        )
        for agent in delegates
    ]
