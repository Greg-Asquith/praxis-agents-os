# apps/api/services/agent_runs/claim_approval_continuation.py

"""Consumes the single start permission for a durable root continuation."""

from uuid import UUID

from pydantic_ai import DeferredToolResults
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from services.agent_runs.continuation_state import (
    DEFERRED_RESULTS_ADAPTER,
    load_approval_continuation,
    store_approval_continuation,
)
from services.agent_runs.execution_state import require_execution_owner
from services.agent_runs.settle_run_family import lock_run_family
from services.agents.runtime.approval_state import SuspendedRunState, load_suspended_run_state
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)


async def claim_approval_continuation(
    db: AsyncSession, *, run_id: UUID, owner_instance_id: str
) -> tuple[SuspendedRunState, DeferredToolResults] | None:
    """Loads accepted decisions once; repeated starts cannot replay approved effects."""
    family = await lock_run_family(db, run_id=run_id)
    if not family or family[0].id != run_id:
        raise ConflictError("The approval root is unavailable", conflicting_resource="agent_run")
    run = family[0]
    require_execution_owner(run, owner_instance_id)
    reservation = load_approval_continuation(run)
    if str(reservation.owner_instance_id) != owner_instance_id:
        raise ConflictError(
            "The approval continuation belongs to another owner", conflicting_resource="agent_run"
        )
    if reservation.phase == "started":
        return None
    suspended = load_suspended_run_state(run)
    results = DEFERRED_RESULTS_ADAPTER.validate_python(reservation.deferred_tool_results)
    reservation.phase = "started"
    store_approval_continuation(run, reservation)
    await safe_record_operation_audit_event(
        db,
        workspace_id=run.workspace_id,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.AGENT_RUN,
        resource_id=run.id,
        actor_type=AuditActorType.SERVICE,
        requested_by_user_id=run.user_id,
        details={
            "operation": "approval_execution_started",
            "generation": str(reservation.generation),
        },
    )
    await db.commit()
    return suspended, results
