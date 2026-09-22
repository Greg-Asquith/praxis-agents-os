# apps/api/services/agent_runs/utils.py

"""Helpers specific to the agent_runs service."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.agent import Agent, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.domain import (
    ALL_RUN_OUTCOMES,
    RUN_OUTCOME_BLOCKED,
    RUN_OUTCOME_BUDGET_EXHAUSTED,
    RUN_OUTCOME_CANCELLED,
    RUN_OUTCOME_ERROR,
    RUN_OUTCOME_SUCCESS,
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_SCHEDULED,
    TERMINAL_RUN_STATUSES,
    RunOutcome,
    can_transition,
)
from services.agents.runtime.approval_state import clear_suspended_run_metadata
from services.agents.runtime.completion_contract import validate_completion_json

if TYPE_CHECKING:
    from services.agents.runtime.approval_projection import DirectApprovalNode
    from services.agents.runtime.tools.contract import RuntimeToolDefinition

MAX_ERROR_MESSAGE_LENGTH = 1000
BLOCKED_ERROR_CODES = frozenset(
    {
        "approval_expired",
        "agent_run_resume_requires_recovery",
        "delegation_requires_recovery",
        "code_mode_resume_requires_recovery",
        "schedule_execution_abandoned",
    }
)


def denial_message_for_model(reason: str | None) -> str:
    """Returns an explicit tool-denial message for the model."""
    if reason:
        return f"The user declined this action, so it was not performed. Reason: {reason}"
    return "The user declined this action, so it was not performed. No reason was given."


def sanitize_error_message(message: str | None) -> str | None:
    """Collapse whitespace and cap length so error text stays operational, not a dump."""
    if message is None:
        return None
    normalized = " ".join(message.split())
    if not normalized:
        return None
    return normalized[:MAX_ERROR_MESSAGE_LENGTH]


def terminal_run_outcome(target: str, *, error_code: str | None = None) -> RunOutcome:
    """Map a terminal execution state and failure code to its operator verdict."""
    if target == RUN_STATUS_COMPLETED:
        return RUN_OUTCOME_SUCCESS
    if target == RUN_STATUS_CANCELLED:
        return RUN_OUTCOME_CANCELLED
    if target != RUN_STATUS_FAILED:
        raise ValueError(f"Cannot derive an outcome for non-terminal status {target!r}")
    if error_code == "usage_limit_exceeded":
        return RUN_OUTCOME_BUDGET_EXHAUSTED
    if error_code in BLOCKED_ERROR_CODES:
        return RUN_OUTCOME_BLOCKED
    return RUN_OUTCOME_ERROR


def failure_completion_json(error_code: str | None) -> dict[str, str]:
    """Return bounded failure taxonomy without copying exception or provider payloads."""
    return {"error_code": error_code or "agent_run_failed"}


async def transition_run_status(
    db: AsyncSession,
    run: AgentRun,
    target: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    outcome: RunOutcome | None = None,
    completion_json: dict[str, Any] | None = None,
) -> AgentRun:
    """Validate and apply a status change, stamping the matching timestamp.

    Shared by every lifecycle operation. A no-op when already at target; raises
    ConflictError for any edge not permitted by domain.ALLOWED_TRANSITIONS.
    """
    # Serialize every transition against the durable row. Callers can hold stale
    # ORM objects while cancellation, reaping, or runtime finalization commits in
    # another session; refreshing under a row lock keeps the first terminal
    # transition authoritative.
    await db.flush()
    await db.refresh(run, with_for_update=True)

    if run.status == target:
        return run
    if not can_transition(run.status, target):
        raise ConflictError(
            f"Cannot move agent run from {run.status!r} to {target!r}",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "from": run.status, "to": target},
        )

    if target not in TERMINAL_RUN_STATUSES and (outcome is not None or completion_json is not None):
        raise ValueError("outcome and completion_json can only be set on a terminal transition")
    if outcome is not None and outcome not in ALL_RUN_OUTCOMES:
        raise ValueError(f"Unknown agent run outcome {outcome!r}")

    resolved_outcome: RunOutcome | None = None
    validated_completion_json: dict[str, Any] | None = None
    if target in TERMINAL_RUN_STATUSES:
        resolved_outcome = outcome or terminal_run_outcome(target, error_code=error_code)
        validated_completion_json = validate_completion_json(
            completion_json
            if completion_json is not None
            else (failure_completion_json(error_code) if target == RUN_STATUS_FAILED else None)
        )

    now = datetime.now(UTC)
    source_status = run.status
    run.status = target
    # Resuming restarts the runtime clock so approval wait time never counts
    # toward the max-duration reap deadline.
    if target == RUN_STATUS_RUNNING and (
        run.started_at is None or source_status == RUN_STATUS_AWAITING_APPROVAL
    ):
        run.started_at = now
    elif target == RUN_STATUS_COMPLETED:
        run.completed_at = now
    elif target == RUN_STATUS_FAILED:
        run.failed_at = now
        run.error_code = error_code
        run.error_message = sanitize_error_message(error_message)
    if target in TERMINAL_RUN_STATUSES:
        reservation = (run.metadata_json or {}).get("approval_continuation")
        if isinstance(reservation, dict):
            await _audit_approval_completion(db, run, reservation, target, resolved_outcome)
        run.metadata_json = clear_suspended_run_metadata(run)
        run.outcome = resolved_outcome
        run.completion_json = validated_completion_json
        run.lease_expires_at = None
    elif target == RUN_STATUS_AWAITING_APPROVAL:
        run.lease_expires_at = None

    await db.flush()
    return run


def _stringify_details(details: dict[str, UUID | str]) -> dict[str, str]:
    return {key: str(value) for key, value in details.items()}


async def validate_run_context(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    agent_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
) -> None:
    """Ensure the IDs used to create a run all belong to the same scope."""
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.deleted == False,  # noqa: E712
        )
    )
    if conversation is None:
        raise NotFoundError(
            "Conversation not found",
            resource_type="conversation",
            resource_id=str(conversation_id),
        )

    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.deleted == False,  # noqa: E712
        )
    )
    if agent is None:
        raise NotFoundError(
            "Agent not found",
            resource_type="agent",
            resource_id=str(agent_id),
        )

    mismatches: dict[str, UUID | str] = {}
    if conversation.workspace_id != workspace_id:
        mismatches["conversation_workspace_id"] = conversation.workspace_id
        mismatches["requested_workspace_id"] = workspace_id
    if conversation.user_id != user_id:
        mismatches["conversation_user_id"] = conversation.user_id
        mismatches["requested_user_id"] = user_id
    if conversation.active_agent_id is not None and conversation.active_agent_id != agent_id:
        mismatches["conversation_active_agent_id"] = conversation.active_agent_id
        mismatches["requested_agent_id"] = agent_id
    if agent.workspace_id != workspace_id:
        mismatches["agent_workspace_id"] = agent.workspace_id
        mismatches["requested_workspace_id"] = workspace_id

    if mismatches:
        raise ConflictError(
            "Agent run context is inconsistent",
            conflicting_resource="agent_run",
            details=_stringify_details(mismatches),
        )


def validate_schedule_run_link(schedule_run: AgentScheduleRun, run: AgentRun) -> None:
    """Ensure a scheduler claim row and generic run describe the same execution."""
    mismatches: dict[str, UUID | str] = {}

    if run.trigger != RUN_TRIGGER_SCHEDULED:
        mismatches["run_trigger"] = run.trigger
        mismatches["expected_trigger"] = RUN_TRIGGER_SCHEDULED
    if schedule_run.agent_run_id is not None and schedule_run.agent_run_id != run.id:
        mismatches["existing_agent_run_id"] = schedule_run.agent_run_id
        mismatches["requested_agent_run_id"] = run.id
    if schedule_run.workspace_id != run.workspace_id:
        mismatches["schedule_run_workspace_id"] = schedule_run.workspace_id
        mismatches["agent_run_workspace_id"] = run.workspace_id
    if schedule_run.user_id != run.user_id:
        mismatches["schedule_run_user_id"] = schedule_run.user_id
        mismatches["agent_run_user_id"] = run.user_id
    if schedule_run.agent_id != run.agent_id:
        mismatches["schedule_run_agent_id"] = schedule_run.agent_id
        mismatches["agent_run_agent_id"] = run.agent_id
    if (
        schedule_run.conversation_id is not None
        and schedule_run.conversation_id != run.conversation_id
    ):
        mismatches["schedule_run_conversation_id"] = schedule_run.conversation_id
        mismatches["agent_run_conversation_id"] = run.conversation_id

    if mismatches:
        raise ConflictError(
            "Schedule run cannot be linked to this agent run",
            conflicting_resource="agent_schedule_run",
            details=_stringify_details(mismatches),
        )


async def _audit_approval_completion(
    db: AsyncSession,
    run: AgentRun,
    reservation: dict[str, Any],
    status: str,
    outcome: RunOutcome | None,
) -> None:
    from services.audit_events.enums import AuditAction, AuditActorType, AuditResourceType
    from services.audit_events.operations import safe_record_operation_audit_event

    generation = reservation.get("generation")
    try:
        generation = str(UUID(str(generation)))
    except (ValueError, TypeError):
        generation = None
    await safe_record_operation_audit_event(
        db,
        workspace_id=run.workspace_id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT_RUN,
        resource_id=run.id,
        actor_type=AuditActorType.SERVICE,
        requested_by_user_id=run.user_id,
        details={
            "operation": "approval_execution_completed",
            "generation": generation,
            "status": status,
            "outcome": outcome,
        },
    )


def validate_retained_review(leaf: "DirectApprovalNode", args: dict[str, Any]) -> None:
    """Requires explicit review when an opted-in selection changes identity."""
    from pydantic import ValidationError

    from services.agents.runtime.entity_references.registry import get_entity_resolver
    from services.agents.runtime.tools.registry import get_runtime_tool_definition

    definition = get_runtime_tool_definition(leaf.call.tool_name)
    if definition is None or not definition.approval_review_fields:
        return
    display = leaf.metadata.get("display_args")
    if not isinstance(display, dict) or "_approval_display_error" in display:
        raise approval_review_required()
    for key in definition.approval_review_fields:
        field = next(field for field in definition.presentation.arg_fields if field.key == key)
        resolver = get_entity_resolver(field.entity_kind)
        selected, reviewed = args.get(key), display.get(key)
        if selected is None:
            continue
        if reviewed is None or resolver is None:
            raise approval_review_required()
        adapter = resolver.reference_adapter()
        try:
            same = (
                adapter.validate_python(selected).identity()
                == adapter.validate_python(reviewed).identity()
            )
        except ValidationError as exc:
            raise approval_review_required() from exc
        if not same:
            raise approval_review_required()


def approval_review_required() -> AppValidationError:
    return AppValidationError(
        "Review the selected File before approving this action.",
        field="source",
        details={"error_code": "approval_review_required"},
    )


async def build_review_display_args(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    run: AgentRun,
    definition: "RuntimeToolDefinition",
    tool_call_id: str,
    canonical: dict[str, Any],
) -> dict[str, Any]:
    """Projects trusted evidence using the owning conversation's authorised context."""
    from inspect import isawaitable

    from pydantic_ai import ModelRetry

    from services.agents.runtime.context import RuntimeDeps
    from services.agents.runtime.entity_references.service import authorize_entity_field
    from services.agents.runtime.envelope import build_run_envelope
    from services.agents.runtime.sinks import NullSink

    authorized = await authorize_entity_field(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        conversation_id=run.conversation_id,
        tool_name=definition.name,
        field_key=definition.approval_review_fields[0],
        run=run,
        tool_call_id=tool_call_id,
    )
    context = authorized.context
    deps = RuntimeDeps(
        db=db,
        user=actor,
        workspace=workspace,
        membership=membership,
        conversation=context.conversation,
        agent=context.agent,
        run=run,
        sink=NullSink(run_id=run.id, conversation_id=run.conversation_id),
        envelope=build_run_envelope(run),
        active_context=context.active_context,
        delegation_depth=run.delegation_depth,
    )
    try:
        projected = definition.approval_display_args(deps, canonical)
        display = await projected if isawaitable(projected) else projected
    except ModelRetry as exc:
        raise AppValidationError(str(exc), field="source") from exc
    return display
