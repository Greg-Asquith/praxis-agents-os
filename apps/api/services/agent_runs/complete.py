# apps/api/services/agent_runs/complete.py

"""Mark a run completed."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_COMPLETED
from services.agent_runs.utils import transition_run_status


async def complete_agent_run(db: AsyncSession, run: AgentRun) -> AgentRun:
    """Mark a run completed successfully."""
    return await transition_run_status(db, run, RUN_STATUS_COMPLETED)
