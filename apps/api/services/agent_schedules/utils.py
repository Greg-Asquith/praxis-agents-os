# apps/api/services/agent_schedules/utils.py

"""Helpers specific to agent schedule services."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from core.exceptions.general import AppValidationError, NotFoundError
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.user import User
from models.workspace import Workspace
from services.agent_schedules.domain import ScheduleConfig, normalize_schedule_config
from services.integrations.context.schemas import ActiveContextTargets
from services.integrations.context.utils import validate_active_context_targets

TIMING_FIELD_NAMES = frozenset(
    {"schedule_type", "cron_expression", "interval_minutes", "run_once_at", "timezone"}
)


def latest_schedule_run_subquery(
    *,
    schedule_ids: Sequence[UUID] | None = None,
    workspace_id: UUID | None = None,
) -> Subquery:
    """Return the canonical latest non-deleted run row for each schedule."""

    filters = [AgentScheduleRun.deleted == False]  # noqa: E712
    if schedule_ids is not None:
        filters.append(AgentScheduleRun.schedule_id.in_(schedule_ids))
    if workspace_id is not None:
        filters.append(AgentScheduleRun.workspace_id == workspace_id)

    ranked_runs = (
        select(
            AgentScheduleRun.id,
            AgentScheduleRun.schedule_id,
            AgentScheduleRun.status,
            AgentScheduleRun.agent_run_id,
            func.row_number()
            .over(
                partition_by=AgentScheduleRun.schedule_id,
                order_by=(
                    AgentScheduleRun.scheduled_for.desc(),
                    AgentScheduleRun.created_at.desc(),
                ),
            )
            .label("latest_run_rank"),
        )
        .where(*filters)
        .subquery()
    )
    return (
        select(
            ranked_runs.c.id,
            ranked_runs.c.schedule_id,
            ranked_runs.c.status,
            ranked_runs.c.agent_run_id,
        )
        .where(ranked_runs.c.latest_run_rank == 1)
        .subquery()
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


async def validate_schedule_active_context(
    db: AsyncSession,
    *,
    selection: ActiveContextTargets | None,
    actor: User,
    workspace: Workspace,
) -> dict[str, object] | None:
    if selection is None:
        return None
    await validate_active_context_targets(
        db,
        targets=selection,
        actor=actor,
        workspace=workspace,
    )
    return selection.model_dump(mode="json")


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
