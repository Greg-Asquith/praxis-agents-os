# apps/api/services/agent_runs/start_with_lease.py

"""Move a run into the running state and stamp its live lease."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_RUNNING
from services.agent_runs.utils import transition_run_status


async def start_agent_run_with_lease(
    db: AsyncSession,
    run: AgentRun,
    *,
    owner_instance_id: str | None = None,
    now: datetime | None = None,
    ttl_seconds: int | None = None,
) -> AgentRun:
    """Begin execution and give the worker a renewable lease in one transaction."""
    await transition_run_status(db, run, RUN_STATUS_RUNNING)

    now_utc = now or datetime.now(UTC)
    ttl = ttl_seconds if ttl_seconds is not None else settings.AGENT_RUN_LEASE_TTL_SECONDS
    run.lease_expires_at = now_utc + timedelta(seconds=ttl)
    if owner_instance_id is not None:
        run.owner_instance_id = owner_instance_id

    await db.flush()
    return run
