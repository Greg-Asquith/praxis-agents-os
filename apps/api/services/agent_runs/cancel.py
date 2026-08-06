# apps/api/services/agent_runs/cancel.py

"""Cancel a non-terminal run."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_CANCELLED, RunOutcome
from services.agent_runs.utils import transition_run_status


async def cancel_agent_run(
    db: AsyncSession,
    run: AgentRun,
    *,
    outcome: RunOutcome | None = None,
    completion_json: dict[str, Any] | None = None,
) -> AgentRun:
    """Cancel a non-terminal run."""
    return await transition_run_status(
        db,
        run,
        RUN_STATUS_CANCELLED,
        outcome=outcome,
        completion_json=completion_json,
    )
