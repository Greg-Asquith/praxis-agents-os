# apps/api/services/agent_schedules/utils.py

"""Helpers specific to agent schedule services."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.agent import Agent, AgentSchedule
from models.workspace import Workspace
from services.agent_schedules.domain import ScheduleConfig, normalize_schedule_config

TIMING_FIELD_NAMES = frozenset(
    {"schedule_type", "cron_expression", "interval_minutes", "run_once_at", "timezone"}
)


async def get_schedule_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    schedule_id: UUID,
) -> AgentSchedule:
    schedule = await db.scalar(
        select(AgentSchedule).where(
            AgentSchedule.id == schedule_id,
            AgentSchedule.workspace_id == workspace.id,
            AgentSchedule.deleted == False,  # noqa: E712
        )
    )
    if schedule is None:
        raise NotFoundError(
            "Agent schedule not found",
            resource_type="agent_schedule",
            resource_id=str(schedule_id),
        )
    return schedule


async def require_active_agent_for_schedule(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent_id: UUID,
) -> Agent:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
            Agent.is_active.is_(True),
        )
    )
    if agent is None:
        raise AppValidationError(
            "Agent must exist in this workspace and be active",
            field="agent_id",
        )
    return agent


def normalize_default_prompt(value: str | None) -> str:
    if value is None:
        raise AppValidationError("default_prompt cannot be null", field="default_prompt")
    normalized = value.strip()
    if not normalized:
        raise AppValidationError("default_prompt must not be blank", field="default_prompt")
    return normalized


def normalize_schedule_name(value: str | None) -> str:
    if value is None:
        raise AppValidationError("name cannot be null", field="name")
    normalized = value.strip()
    if not normalized:
        raise AppValidationError("name must not be blank", field="name")
    return normalized


def normalize_schedule_from_row(
    schedule: AgentSchedule,
    *,
    require_future_once: bool = True,
) -> ScheduleConfig:
    return normalize_schedule_config(
        schedule_type=schedule.schedule_type,
        cron_expression=schedule.cron_expression,
        interval_minutes=schedule.interval_minutes,
        run_once_at=schedule.run_once_at,
        timezone=schedule.timezone,
        require_future_once=require_future_once,
    )


def set_if_changed(
    entity: object,
    field_name: str,
    value: object,
    changed_fields: list[str],
) -> None:
    if getattr(entity, field_name) != value:
        setattr(entity, field_name, value)
        changed_fields.append(field_name)
