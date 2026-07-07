# apps/api/services/agents/list_agents.py

"""List agents visible in a workspace."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.workspace import Workspace
from services.agents.schemas import AgentRead, AgentsListResponse
from utils.pagination import paginate


async def list_agents(
    db: AsyncSession,
    *,
    workspace: Workspace,
    limit: int,
    offset: int,
    include_inactive: bool,
) -> AgentsListResponse:
    filters = [
        Agent.workspace_id == workspace.id,
        Agent.deleted == False,  # noqa: E712
    ]
    if not include_inactive:
        filters.append(Agent.is_active.is_(True))

    agents, total = await paginate(
        db,
        select(Agent).where(*filters),
        Agent.is_favorite.desc(),
        Agent.last_used_at.desc().nullslast(),
        Agent.created_at.desc(),
        limit=limit,
        offset=offset,
    )

    return AgentsListResponse(
        agents=[AgentRead.from_agent(agent) for agent in agents],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
