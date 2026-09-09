# apps/api/services/agent_runs/claim_child_approval.py

"""Claims a reserved specialist batch only when its parent reaches that call."""

from pydantic_ai import DeferredToolResults
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.continuation_state import (
    AgentRunResumeRequiresRecoveryError,
    load_approval_continuation,
    store_approval_continuation,
)
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.execution_state import require_execution_owner
from services.agent_runs.start_with_lease import start_agent_run_with_lease
from services.agents.delegation_approval import DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY
from services.agents.runtime.approval_identity import proposal_digest
from services.agents.runtime.approval_state import load_suspended_run_state


async def claim_child_approval(
    db: AsyncSession,
    *,
    root: AgentRun,
    child: AgentRun,
    parent_tool_call_id: str,
    root_owner: str,
    child_owner: str,
    results: DeferredToolResults,
) -> None:
    """Consumes one child batch under the caller's root-first family locks."""
    require_execution_owner(root, root_owner)
    reservation = load_approval_continuation(root)
    if (
        reservation.phase != "started"
        or str(reservation.owner_instance_id) != root_owner
        or child.parent_run_id != root.id
        or child.status != RUN_STATUS_AWAITING_APPROVAL
        or child.id not in reservation.child_batches
        or child.id in reservation.claimed_child_ids
    ):
        raise AgentRunResumeRequiresRecoveryError()
    suspended = load_suspended_run_state(child)
    if reservation.child_batches[child.id] != suspended.approval_batch_id:
        raise AgentRunResumeRequiresRecoveryError()
    metadata = reservation.deferred_tool_results.get("metadata", {}).get(parent_tool_call_id, {})
    saved_results = metadata.get(DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY)
    if metadata.get("child_run_id") != str(child.id) or proposal_digest(
        saved_results
    ) != proposal_digest(to_jsonable_python(results)):
        raise AgentRunResumeRequiresRecoveryError()
    reservation.claimed_child_ids.append(child.id)
    store_approval_continuation(root, reservation)
    await start_agent_run_with_lease(db, child, owner_instance_id=child_owner)
    await db.commit()
