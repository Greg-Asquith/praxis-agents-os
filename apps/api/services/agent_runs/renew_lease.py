# apps/api/services/agent_runs/renew_lease.py

"""Renew the live lease for an agent run."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_PENDING, RUN_STATUS_RUNNING


async def renew_agent_run_lease(
    db: AsyncSession,
    *,
    run_id: UUID,
    owner_instance_id: str | None = None,
    now: datetime | None = None,
    ttl_seconds: int | None = None,
) -> bool:
    """Extend a pending/running run lease and return whether a row was updated."""
    now_utc = now or datetime.now(UTC)
    ttl = ttl_seconds if ttl_seconds is not None else settings.AGENT_RUN_LEASE_TTL_SECONDS
    values = {"lease_expires_at": now_utc + timedelta(seconds=ttl)}
    if owner_instance_id is not None:
        values["owner_instance_id"] = owner_instance_id

    result = await db.execute(
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.deleted == False,  # noqa: E712
            AgentRun.status.in_({RUN_STATUS_PENDING, RUN_STATUS_RUNNING}),
        )
        .values(**values)
    )
    await db.flush()
    return bool(result.rowcount)
