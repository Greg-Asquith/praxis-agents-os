# apps/api/services/agent_runs/start_with_lease.py

"""Move a run into the running state and stamp its live lease."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from services.agent_runs.claim_execution import claim_agent_run_execution
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_STATUS_RUNNING
from services.agent_runs.utils import transition_run_status


async def start_agent_run_with_lease(
    db: AsyncSession,
    run: AgentRun,
    *,
    owner_instance_id: str | None = None,
    now: datetime | None = None,
    ttl_seconds: int | None = None,
) -> AgentRun:
    """Starts a claimed invocation, or explicitly claims an unowned continuation."""
    await db.flush()
    await db.refresh(run, with_for_update=True)
    now_utc = now or datetime.now(UTC)
    owner = owner_instance_id or str(uuid4())
    if run.owner_instance_id is None or run.status == RUN_STATUS_AWAITING_APPROVAL:
        await claim_agent_run_execution(
            db, run, owner_instance_id=owner, now=now_utc, ttl_seconds=ttl_seconds
        )
    elif (
        run.owner_instance_id != owner
        or run.lease_expires_at is None
        or run.lease_expires_at <= now_utc
    ):
        raise ConflictError(
            "Agent run execution lease is no longer owned", conflicting_resource="agent_run"
        )
    return await transition_run_status(db, run, RUN_STATUS_RUNNING)
