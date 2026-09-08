# apps/api/services/agent_runs/approval_expiry.py

"""Resolves the shared consent deadline for an approval family."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.continuation_state import load_approval_continuation


def approval_family_deadline(
    family: list[AgentRun], *, expiry_days: int | None = None
) -> datetime | None:
    """Returns the earliest pending deadline; zero disables approval expiry."""
    days = settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS if expiry_days is None else expiry_days
    if days == 0:
        return None
    if days < 0:
        raise ValueError("expiry_days must be greater than or equal to zero")
    deadlines = [
        run.updated_at + timedelta(days=days) for run in family if run.status == "awaiting_approval"
    ]
    return min(deadlines, default=None)


async def read_approval_family_deadline(db: AsyncSession, *, run: AgentRun) -> datetime | None:
    """Reads the same scoped family deadline used by locked approval mutations."""
    root_id = run.parent_run_id or run.id
    family = list(
        await db.scalars(
            select(AgentRun).where(
                (AgentRun.id == root_id) | (AgentRun.parent_run_id == root_id),
                AgentRun.workspace_id == run.workspace_id,
                AgentRun.user_id == run.user_id,
                AgentRun.deleted.is_(False),
            )
        )
    )
    root = next((item for item in family if item.id == root_id), None)
    if root is None or root.status != "awaiting_approval":
        return None
    return approval_family_deadline(family)


def has_live_approval_reservation(
    root: AgentRun, *, family: list[AgentRun] | None = None, now: datetime | None = None
) -> bool:
    """Checks the execution owner and deadlines before protecting queued approvals."""
    now = now or datetime.now(UTC)
    try:
        reservation = load_approval_continuation(root)
    except ConflictError:
        return False
    if family is not None:
        children = {run.id: run for run in family if run.parent_run_id == root.id}
        for child_id, batch_id in reservation.child_batches.items():
            child = children.get(child_id)
            if child is None:
                return False
            if child.status == "awaiting_approval":
                state = (child.metadata_json or {}).get("approval_state")
                saved_batch = state.get("approval_batch_id") if isinstance(state, dict) else None
                if saved_batch != (str(batch_id) if batch_id is not None else None):
                    return False
    return bool(
        str(reservation.owner_instance_id) == root.owner_instance_id
        and root.owner_instance_id
        and root.status == "running"
        and root.lease_expires_at is not None
        and root.lease_expires_at > now
        and root.started_at is not None
        and root.started_at + timedelta(seconds=settings.AGENT_RUN_MAX_DURATION_SECONDS) > now
    )
