# apps/api/services/agent_schedules/update_schedule.py

"""Update a workspace-scoped agent schedule."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_schedules.authorisation import assert_can_mutate_schedule
from services.agent_schedules.domain import (
    ScheduleConfig,
    calculate_next_run,
    normalize_schedule_config,
)
from services.agent_schedules.runs import get_latest_runs_by_schedule_ids
from services.agent_schedules.schemas import AgentScheduleRead, AgentScheduleUpdateRequest
from services.agent_schedules.utils import (
    TIMING_FIELD_NAMES,
    get_schedule_for_workspace,
    normalize_default_prompt,
    normalize_schedule_from_row,
    set_if_changed,
)
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def update_schedule(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    schedule_id: UUID,
    payload: AgentScheduleUpdateRequest,
) -> AgentScheduleRead:
    schedule = await get_schedule_for_workspace(db, workspace=workspace, schedule_id=schedule_id)
    assert_can_mutate_schedule(schedule=schedule, current_user=actor, membership=membership)

    changed_fields: list[str] = []
    timing_fields = set(payload.model_fields_set).intersection(TIMING_FIELD_NAMES)
    config: ScheduleConfig | None = None
    was_active = schedule.is_active

    if timing_fields:
        config = _normalize_timing_update(schedule, payload, supplied_fields=timing_fields)
        _apply_config(schedule, config, changed_fields)

    if "default_prompt" in payload.model_fields_set:
        set_if_changed(
            schedule,
            "default_prompt",
            normalize_default_prompt(payload.default_prompt),
            changed_fields,
        )

    if "execution_params" in payload.model_fields_set:
        set_if_changed(schedule, "execution_params", payload.execution_params, changed_fields)

    if "is_active" in payload.model_fields_set:
        if payload.is_active is None:
            raise AppValidationError("is_active cannot be null", field="is_active")
        set_if_changed(schedule, "is_active", payload.is_active, changed_fields)
        if payload.is_active and (not was_active or config is not None):
            config = config or normalize_schedule_from_row(schedule)
            set_if_changed(
                schedule,
                "next_run_at",
                calculate_next_run(config, basis=datetime.now(UTC)),
                changed_fields,
            )
        elif not payload.is_active:
            set_if_changed(schedule, "next_run_at", None, changed_fields)
    elif config is not None:
        set_if_changed(
            schedule,
            "next_run_at",
            calculate_next_run(config) if schedule.is_active else None,
            changed_fields,
        )

    if changed_fields:
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.AGENT_SCHEDULE,
            resource_id=schedule.id,
            actor=actor,
            details={
                "agent_id": str(schedule.agent_id),
                "schedule_type": schedule.schedule_type,
                "timezone": schedule.timezone,
                "changed_fields": changed_fields,
            },
        )
        await db.refresh(schedule)

    latest_runs = await get_latest_runs_by_schedule_ids(db, [schedule.id])
    return AgentScheduleRead.from_schedule(schedule, latest_run=latest_runs.get(schedule.id))


def _normalize_timing_update(
    schedule,
    payload: AgentScheduleUpdateRequest,
    *,
    supplied_fields: set[str],
) -> ScheduleConfig:
    if "schedule_type" in payload.model_fields_set and payload.schedule_type is None:
        raise AppValidationError("schedule_type cannot be null", field="schedule_type")

    return normalize_schedule_config(
        schedule_type=(
            payload.schedule_type
            if "schedule_type" in payload.model_fields_set
            else schedule.schedule_type
        ),
        cron_expression=(
            payload.cron_expression
            if "cron_expression" in payload.model_fields_set
            else schedule.cron_expression
        ),
        interval_minutes=(
            payload.interval_minutes
            if "interval_minutes" in payload.model_fields_set
            else schedule.interval_minutes
        ),
        run_once_at=(
            payload.run_once_at
            if "run_once_at" in payload.model_fields_set
            else schedule.run_once_at
        ),
        timezone=payload.timezone if "timezone" in payload.model_fields_set else schedule.timezone,
        supplied_fields=supplied_fields,
    )


def _apply_config(schedule, config: ScheduleConfig, changed_fields: list[str]) -> None:
    for field_name, value in (
        ("schedule_type", config.schedule_type),
        ("cron_expression", config.cron_expression),
        ("interval_minutes", config.interval_minutes),
        ("run_once_at", config.run_once_at),
        ("timezone", config.timezone),
    ):
        set_if_changed(schedule, field_name, value, changed_fields)
