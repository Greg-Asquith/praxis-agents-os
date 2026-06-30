# apps/api/services/agents/list_agents.py

"""List agents visible in a workspace."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.workspace import Workspace
from services.agents.schemas import AgentRead, AgentsListResponse


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

    total = await db.scalar(select(func.count()).select_from(Agent).where(*filters))
    agents = (
        await db.scalars(
            select(Agent)
            .where(*filters)
            .order_by(
                Agent.is_favorite.desc(),
                Agent.last_used_at.desc().nullslast(),
                Agent.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return AgentsListResponse(
        agents=[AgentRead.from_agent(agent) for agent in agents],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
