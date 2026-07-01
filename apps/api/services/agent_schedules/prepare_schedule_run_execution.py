# apps/api/services/agent_schedules/prepare_schedule_run_execution.py

"""Prepare one claimed schedule run for runtime execution."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs import create_agent_run, link_schedule_run
from services.agent_runs.domain import RUN_TRIGGER_SCHEDULED
from services.agent_schedules.runs import (
    RUN_STATUS_CLAIMED,
    RUN_STATUS_RUNNING,
    mark_run_terminal_failure_and_disable_schedule,
)
from services.conversations.naming import fallback_conversation_title
from utils.dates import normalize_utc_datetime


@dataclass(frozen=True)
class PreparedScheduleRunExecution:
    """Durable IDs needed to execute one scheduled turn."""

    schedule_id: UUID
    schedule_run_id: UUID
    conversation_id: UUID | None
    agent_run_id: UUID | None
    user_prompt: str | None

    @property
    def should_execute(self) -> bool:
        return (
            self.conversation_id is not None
            and self.agent_run_id is not None
            and self.user_prompt is not None
        )


async def prepare_schedule_run_execution(
    db: AsyncSession,
    *,
    schedule_run_id: UUID,
    now: datetime | None = None,
) -> PreparedScheduleRunExecution:
    """Create the conversation/run handoff for one claimed schedule run."""
    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)
    schedule_run = await _load_schedule_run_for_update(db, schedule_run_id)
    schedule = await _load_schedule_for_update(db, schedule_run.schedule_id)
    agent = await _load_agent(db, schedule.agent_id)

    if schedule_run.status != RUN_STATUS_CLAIMED:
        raise ConflictError(
            "Schedule run is not claimed for execution",
            conflicting_resource="agent_schedule_run",
            details={
                "schedule_run_id": str(schedule_run.id),
                "status": schedule_run.status,
            },
        )

    prompt = " ".join((schedule.default_prompt or "").split())
    if not prompt:
        await mark_run_terminal_failure_and_disable_schedule(
            db,
            schedule,
            schedule_run,
            now=now_utc,
            code="missing_default_prompt",
            message="Schedule has no default prompt to execute.",
        )
        await db.flush()
        return PreparedScheduleRunExecution(
            schedule_id=schedule.id,
            schedule_run_id=schedule_run.id,
            conversation_id=None,
            agent_run_id=None,
            user_prompt=None,
        )

    conversation = await _ensure_conversation(
        db,
        schedule=schedule,
        schedule_run=schedule_run,
        agent=agent,
        prompt=prompt,
    )
    run = await _ensure_agent_run(
        db,
        schedule=schedule,
        schedule_run=schedule_run,
        conversation=conversation,
    )

    schedule_run.status = RUN_STATUS_RUNNING
    schedule_run.accepted_at = now_utc
    schedule_run.claim_expires_at = None
    schedule_run.last_error_code = None
    schedule_run.last_error_message = None
    await db.flush()
    return PreparedScheduleRunExecution(
        schedule_id=schedule.id,
        schedule_run_id=schedule_run.id,
        conversation_id=conversation.id,
        agent_run_id=run.id,
        user_prompt=prompt,
    )


async def _load_schedule_run_for_update(
    db: AsyncSession,
    schedule_run_id: UUID,
) -> AgentScheduleRun:
    schedule_run = await db.scalar(
        select(AgentScheduleRun)
        .where(
            AgentScheduleRun.id == schedule_run_id,
            AgentScheduleRun.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    if schedule_run is None:
        raise NotFoundError(
            "Schedule run not found",
            resource_type="agent_schedule_run",
            resource_id=str(schedule_run_id),
        )
    return schedule_run


async def _load_schedule_for_update(db: AsyncSession, schedule_id: UUID) -> AgentSchedule:
    schedule = await db.scalar(
        select(AgentSchedule)
        .where(
            AgentSchedule.id == schedule_id,
            AgentSchedule.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    if schedule is None:
        raise NotFoundError(
            "Schedule not found",
            resource_type="agent_schedule",
            resource_id=str(schedule_id),
        )
    return schedule


async def _load_agent(db: AsyncSession, agent_id: UUID) -> Agent:
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
    return agent


async def _ensure_conversation(
    db: AsyncSession,
    *,
    schedule: AgentSchedule,
    schedule_run: AgentScheduleRun,
    agent: Agent,
    prompt: str,
) -> Conversation:
    if schedule_run.conversation_id is not None:
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.id == schedule_run.conversation_id,
                Conversation.deleted == False,  # noqa: E712
            )
        )
        if conversation is None:
            raise NotFoundError(
                "Scheduled conversation not found",
                resource_type="conversation",
                resource_id=str(schedule_run.conversation_id),
            )
        return conversation

    conversation = Conversation(
        user_id=schedule.user_id,
        workspace_id=schedule.workspace_id,
        created_by=schedule.user_id,
        title=fallback_conversation_title(prompt),
        source="scheduled",
        schedule_id=schedule.id,
        schedule_run_id=schedule_run.id,
        active_agent_id=schedule.agent_id,
        agent_slug=agent.slug,
        metadata_json={
            "schedule": {
                "schedule_id": str(schedule.id),
                "schedule_run_id": str(schedule_run.id),
                "scheduled_for": schedule_run.scheduled_for.isoformat(),
            }
        },
    )
    db.add(conversation)
    await db.flush()
    schedule_run.conversation_id = conversation.id
    return conversation


async def _ensure_agent_run(
    db: AsyncSession,
    *,
    schedule: AgentSchedule,
    schedule_run: AgentScheduleRun,
    conversation: Conversation,
) -> AgentRun:
    if schedule_run.agent_run_id is not None:
        run = await db.scalar(
            select(AgentRun).where(
                AgentRun.id == schedule_run.agent_run_id,
                AgentRun.deleted == False,  # noqa: E712
            )
        )
        if run is None:
            raise NotFoundError(
                "Linked agent run not found",
                resource_type="agent_run",
                resource_id=str(schedule_run.agent_run_id),
            )
        return run

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=schedule.agent_id,
        workspace_id=schedule.workspace_id,
        user_id=schedule.user_id,
        trigger=RUN_TRIGGER_SCHEDULED,
        metadata={
            "schedule_id": str(schedule.id),
            "schedule_run_id": str(schedule_run.id),
            "scheduled_for": schedule_run.scheduled_for.isoformat(),
        },
    )
    await link_schedule_run(db, schedule_run, run)
    return run
