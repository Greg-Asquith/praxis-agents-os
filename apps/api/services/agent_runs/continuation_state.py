# apps/api/services/agent_runs/continuation_state.py

"""Validates bounded, owner-bound approval continuation reservations."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied

from models.agent_run import AgentRun
from services.agent_runs.schemas import AgentRunResumeRequest
from services.agents.runtime.approval_identity import (
    MAX_PROJECTION_LEAVES,
    invalid_approval_state,
    proposal_digest,
)

CONTINUATION_KEY = "approval_continuation"
DEFERRED_RESULTS_ADAPTER = TypeAdapter(DeferredToolResults)


class ApprovalContinuation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    generation: UUID
    owner_instance_id: UUID
    approval_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    child_batches: dict[UUID, UUID | None] = Field(max_length=MAX_PROJECTION_LEAVES)
    claimed_child_ids: list[UUID] = Field(default_factory=list, max_length=MAX_PROJECTION_LEAVES)
    deferred_tool_results: dict[str, Any]
    phase: Literal["reserved", "started"] = "reserved"


def load_approval_continuation(run: AgentRun) -> ApprovalContinuation:
    """Checks size and schema before exposing durable executable decisions."""
    raw = (run.metadata_json or {}).get(CONTINUATION_KEY)
    proposal_digest(raw)
    try:
        reservation = ApprovalContinuation.model_validate(raw)
        DEFERRED_RESULTS_ADAPTER.validate_python(reservation.deferred_tool_results)
    except (ValidationError, TypeError, ValueError) as exc:
        raise invalid_approval_state("Saved approval continuation is invalid") from exc
    if len(set(reservation.claimed_child_ids)) != len(reservation.claimed_child_ids) or not set(
        reservation.claimed_child_ids
    ).issubset(reservation.child_batches):
        raise invalid_approval_state("Saved approval child claims are invalid")
    return reservation


def resume_request_digest(payload: AgentRunResumeRequest) -> str:
    """Compares submissions without storing another copy of reviewed arguments."""
    raw = payload.model_dump(mode="json")
    raw["decisions"] = sorted(
        raw["decisions"], key=lambda item: (item.get("approval_id") or "", item["tool_call_id"])
    )
    return proposal_digest(raw)


def store_approval_continuation(run: AgentRun, reservation: ApprovalContinuation) -> None:
    """Stores a reservation within the shared four-megabyte proposal ceiling."""
    raw = reservation.model_dump(mode="json")
    proposal_digest(raw)
    run.metadata_json = {**(run.metadata_json or {}), CONTINUATION_KEY: raw}


def denied_approval_calls(*, root: AgentRun, run: AgentRun) -> set[str]:
    """Excludes proven denials from uncertainty for the matching saved batch."""
    from core.exceptions.general import ConflictError
    from services.agents.delegation_approval import (
        DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY,
    )
    from services.agents.runtime.approval_state import load_suspended_run_state
    from services.agents.runtime.code_mode.approval import (
        CODE_MODE_DECISION_KEY,
        code_mode_nested_call,
    )

    try:
        reservation = load_approval_continuation(root)
        results = DEFERRED_RESULTS_ADAPTER.validate_python(reservation.deferred_tool_results)
        if run.id != root.id:
            state = load_suspended_run_state(run)
            if (
                run.parent_run_id != root.id
                or run.id not in reservation.child_batches
                or reservation.child_batches[run.id] != state.approval_batch_id
            ):
                return set()
            child_results = [
                metadata[DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY]
                for metadata in results.metadata.values()
                if metadata.get("child_run_id") == str(run.id)
                and DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY in metadata
            ]
            if len(child_results) != 1:
                return set()
            results = DEFERRED_RESULTS_ADAPTER.validate_python(child_results[0])
    except (ConflictError, ValidationError, TypeError, ValueError):
        return set()
    denied = {
        call_id
        for call_id, decision in results.approvals.items()
        if isinstance(decision, ToolDenied)
    }
    for call_id, metadata in results.metadata.items():
        decision = metadata.get(CODE_MODE_DECISION_KEY)
        nested = code_mode_nested_call(metadata)
        if (
            isinstance(results.approvals.get(call_id), ToolApproved)
            and nested is not None
            and isinstance(decision, dict)
            and decision.get("decision") == "denied"
            and decision.get("nested_tool_call_id") == nested.tool_call_id
        ):
            denied.add(nested.tool_call_id)
    return denied


class AgentRunResumeRequiresRecoveryError(RuntimeError):
    """Stops model execution when a continuation cannot be proved safe."""

    def __init__(self, completion_json: dict[str, Any] | None = None):
        super().__init__("Review the previous actions before continuing this conversation.")
        self.completion_json = completion_json
