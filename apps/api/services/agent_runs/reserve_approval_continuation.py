# apps/api/services/agent_runs/reserve_approval_continuation.py

"""Reserves validated decisions and execution ownership in one transaction."""

from collections.abc import Mapping
from uuid import UUID, uuid4

from pydantic_ai import DeferredToolResults
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.continuation_state import (
    ApprovalContinuation,
    resume_request_digest,
    store_approval_continuation,
)
from services.agent_runs.schemas import AgentRunResumeRequest
from services.agent_runs.start_with_lease import start_agent_run_with_lease
from services.agents.runtime.approval_projection import ApprovalGraph, DelegatedApprovalNode
from services.agents.runtime.approval_state import load_suspended_run_state
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)


async def reserve_approval_continuation(
    db: AsyncSession,
    *,
    run: AgentRun,
    graph: ApprovalGraph,
    runs: Mapping[UUID, AgentRun],
    payload: AgentRunResumeRequest,
    revision: str,
    results: DeferredToolResults,
) -> ApprovalContinuation:
    """Persists bounded consent before claiming the locked root for queueing."""
    reservation = ApprovalContinuation(
        generation=uuid4(),
        owner_instance_id=uuid4(),
        approval_revision=revision,
        request_digest=resume_request_digest(payload),
        child_batches={
            node.child_run_id: load_suspended_run_state(runs[node.child_run_id]).approval_batch_id
            for node in graph.nodes
            if isinstance(node, DelegatedApprovalNode) and node.child_run_id is not None
        },
        deferred_tool_results=to_jsonable_python(results),
    )
    # Validate the complete envelope before changing any run or execution clock.
    store_approval_continuation(run, reservation)
    await start_agent_run_with_lease(db, run, owner_instance_id=str(reservation.owner_instance_id))
    await safe_record_operation_audit_event(
        db,
        workspace_id=run.workspace_id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT_RUN,
        resource_id=run.id,
        actor_type=AuditActorType.USER,
        actor_id=run.user_id,
        requested_by_user_id=run.user_id,
        details={
            "operation": "approval_accepted",
            "generation": str(reservation.generation),
            "approval_revision": revision,
            "decision_count": len(payload.decisions),
            "child_count": len(reservation.child_batches),
        },
    )
    return reservation
