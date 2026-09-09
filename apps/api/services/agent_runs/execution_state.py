# apps/api/services/agent_runs/execution_state.py

"""Reads durable execution permission in an isolated tenant transaction."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from core.exceptions.general import ConflictError
from models.agent_run import AgentRun


@dataclass(frozen=True)
class ExecutionState:
    """Contains only the fields needed to fence an invocation."""

    status: str
    owner_instance_id: str | None
    lease_expires_at: datetime | None


async def read_execution_states(
    *, run_ids: tuple[UUID, ...], workspace_id: UUID, user_id: UUID
) -> dict[UUID, ExecutionState]:
    """Reads the invocation and controlling root from one fresh database snapshot."""
    async with get_async_db_session_factory()() as db:
        await configure_async_db_session(db)
        await set_session_tenant_context(db, workspace_id=workspace_id, user_id=user_id)
        rows = await db.execute(
            select(
                AgentRun.id, AgentRun.status, AgentRun.owner_instance_id, AgentRun.lease_expires_at
            ).where(
                AgentRun.id.in_(run_ids),
                AgentRun.workspace_id == workspace_id,
                AgentRun.user_id == user_id,
                AgentRun.deleted.is_(False),
            )
        )
        return {
            row.id: ExecutionState(row.status, row.owner_instance_id, row.lease_expires_at)
            for row in rows
        }


def require_execution_owner(run: AgentRun, owner_instance_id: str) -> None:
    """Checks an already locked live owner before creating or resuming dependent work."""
    if (
        run.deleted
        or run.status not in {"pending", "running"}
        or run.owner_instance_id != owner_instance_id
        or run.lease_expires_at is None
        or run.lease_expires_at <= datetime.now(UTC)
    ):
        raise ConflictError(
            "Agent run execution is no longer owned", conflicting_resource="agent_run"
        )
