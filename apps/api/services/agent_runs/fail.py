# apps/api/services/agent_runs/fail.py

"""Mark a run failed."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_FAILED
from services.agent_runs.utils import transition_run_status


async def fail_agent_run(
    db: AsyncSession,
    run: AgentRun,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> AgentRun:
    """Mark a run failed, recording concise error context."""
    return await transition_run_status(
        db, run, RUN_STATUS_FAILED, error_code=error_code, error_message=error_message
    )
