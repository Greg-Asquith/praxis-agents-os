# apps/api/services/agent_runs/complete.py

"""Mark a run completed."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_COMPLETED, RunOutcome, is_terminal
from services.agent_runs.utils import transition_run_status


async def complete_agent_run(
    db: AsyncSession,
    run: AgentRun,
    *,
    outcome: RunOutcome | None = None,
    completion_json: dict[str, Any] | None = None,
) -> AgentRun:
    """Mark a run completed successfully."""
    if is_terminal(run.status):
        return run
    return await transition_run_status(
        db,
        run,
        RUN_STATUS_COMPLETED,
        outcome=outcome,
        completion_json=completion_json,
    )
