# apps/api/services/agent_runs/fail.py

"""Mark a run failed."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_FAILED, RunOutcome
from services.agent_runs.utils import transition_run_status


async def fail_agent_run(
    db: AsyncSession,
    run: AgentRun,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    outcome: RunOutcome | None = None,
    completion_json: dict[str, Any] | None = None,
) -> AgentRun:
    """Mark a run failed, recording concise error context."""
    return await transition_run_status(
        db,
        run,
        RUN_STATUS_FAILED,
        error_code=error_code,
        error_message=error_message,
        outcome=outcome,
        completion_json=completion_json,
    )
