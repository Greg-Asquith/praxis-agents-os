# apps/api/services/agent_runs/cancel.py

"""Cancel a non-terminal run."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_CANCELLED
from services.agent_runs.utils import transition_run_status


async def cancel_agent_run(db: AsyncSession, run: AgentRun) -> AgentRun:
    """Cancel a non-terminal run."""
    return await transition_run_status(db, run, RUN_STATUS_CANCELLED)
