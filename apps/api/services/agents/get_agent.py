# apps/api/services/agents/get_agent.py

"""Read a workspace-scoped agent."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.agents.runtime.tools.workspace_tools import (
    load_workspace_tool_definitions,
    workspace_tool_names,
)
from services.agents.schemas import AgentRead
from services.agents.utils import get_agent_for_workspace


async def get_agent(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent_id: UUID,
) -> AgentRead:
    agent = await get_agent_for_workspace(db, workspace=workspace, agent_id=agent_id)
    definitions = await load_workspace_tool_definitions(db, workspace)
    return AgentRead.from_agent(agent, extra_tool_names=workspace_tool_names(definitions))
