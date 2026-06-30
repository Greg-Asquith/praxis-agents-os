# apps/api/services/agent_runs/utils.py

"""Helpers specific to the agent_runs service."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_SCHEDULED,
    can_transition,
)

MAX_ERROR_MESSAGE_LENGTH = 1000


def sanitize_error_message(message: str | None) -> str | None:
    """Collapse whitespace and cap length so error text stays operational, not a dump."""
    if message is None:
        return None
    normalized = " ".join(message.split())
    if not normalized:
        return None
    return normalized[:MAX_ERROR_MESSAGE_LENGTH]


async def transition_run_status(
    db: AsyncSession,
    run: AgentRun,
    target: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> AgentRun:
    """Validate and apply a status change, stamping the matching timestamp.

    Shared by every lifecycle operation. A no-op when already at target; raises
    ConflictError for any edge not permitted by domain.ALLOWED_TRANSITIONS.
    """
    if run.status == target:
        return run
    if not can_transition(run.status, target):
        raise ConflictError(
            f"Cannot move agent run from {run.status!r} to {target!r}",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "from": run.status, "to": target},
        )

    now = datetime.now(UTC)
    run.status = target
    if target == RUN_STATUS_RUNNING and run.started_at is None:
        run.started_at = now
    elif target == RUN_STATUS_COMPLETED:
        run.completed_at = now
    elif target == RUN_STATUS_FAILED:
        run.failed_at = now
        run.error_code = error_code
        run.error_message = sanitize_error_message(error_message)

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
