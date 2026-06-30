# apps/api/services/agent_runs/start.py

"""Move a run into the running state."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_RUNNING
from services.agent_runs.utils import transition_run_status


async def start_agent_run(db: AsyncSession, run: AgentRun) -> AgentRun:
    """Begin (or resume) execution by moving the run into running."""
    return await transition_run_status(db, run, RUN_STATUS_RUNNING)
