# apps/api/services/agents/get_agent.py

"""Read a workspace-scoped agent."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.agents.schemas import AgentRead
from services.agents.utils import get_agent_for_workspace


async def get_agent(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent_id: UUID,
) -> AgentRead:
    agent = await get_agent_for_workspace(db, workspace=workspace, agent_id=agent_id)
    return AgentRead.from_agent(agent)
