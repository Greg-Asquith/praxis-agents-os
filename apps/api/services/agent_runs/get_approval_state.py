# apps/api/services/agent_runs/get_approval_state.py

"""Reads the shared pending approval projection for an agent run."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.agent_runs.schemas import AgentRunApprovalStateResponse


async def get_agent_run_approval_state(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    run_id: UUID,
) -> AgentRunApprovalStateResponse:
    """Returns pending approval leaves without exposing executable run history."""
    from services.agent_runs.load_approval_graph import load_approval_graph
    from services.agents.runtime.approval_projection import project_approval_graph

    graph = await load_approval_graph(db, actor=actor, workspace=workspace, run_id=run_id)
    return project_approval_graph(graph)
