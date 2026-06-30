# apps/api/services/agent_runs/link_schedule_run.py

"""Link a scheduler claim row to its generic run."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import AgentScheduleRun
from models.agent_run import AgentRun
from services.agent_runs.utils import validate_schedule_run_link


async def link_schedule_run(
    db: AsyncSession, schedule_run: AgentScheduleRun, run: AgentRun
) -> AgentScheduleRun:
    """Point a scheduler claim row at the generic run a worker created for it."""
    validate_schedule_run_link(schedule_run, run)
    schedule_run.agent_run_id = run.id
    await db.flush()
    return schedule_run
