# apps/api/services/agent_runs/claim_execution.py

"""Claims one admitted agent-run invocation before work is queued."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
)


async def claim_agent_run_execution(
    db: AsyncSession,
    run: AgentRun,
    *,
    owner_instance_id: str,
    now: datetime | None = None,
    ttl_seconds: int | None = None,
) -> AgentRun:
    """Claims an ownerless run or reserves a parked approval under its row lock."""
    await db.flush()
    await db.refresh(run, with_for_update=True)
    resumable = run.status == RUN_STATUS_AWAITING_APPROVAL
    unclaimed = (
        run.status in {RUN_STATUS_PENDING, RUN_STATUS_RUNNING} and run.owner_instance_id is None
    )
    if run.deleted or not (resumable or unclaimed):
        raise ConflictError(
            "Agent run execution is already claimed or closed", conflicting_resource="agent_run"
        )
    now_utc = now or datetime.now(UTC)
    if run.lease_expires_at is not None and run.lease_expires_at <= now_utc:
        raise ConflictError(
            "Agent run execution lease has expired", conflicting_resource="agent_run"
        )
    if resumable:
        run.status = RUN_STATUS_RUNNING
        run.started_at = now_utc
    elif run.started_at is None:
        run.started_at = run.created_at
    run.owner_instance_id = owner_instance_id
    ttl = ttl_seconds if ttl_seconds is not None else settings.AGENT_RUN_LEASE_TTL_SECONDS
    run.lease_expires_at = now_utc + timedelta(seconds=ttl)
    await db.flush()
    return run
