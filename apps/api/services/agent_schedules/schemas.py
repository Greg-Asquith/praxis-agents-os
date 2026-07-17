# apps/api/services/agent_schedules/schemas.py

"""Pydantic contracts for agent schedule routes."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from models.agent import AgentSchedule, AgentScheduleRun
from services.agent_schedules.runs import schedule_health_from_run
from utils.pagination import OffsetPage
from utils.validation import normalize_optional_text

ScheduleSideEffectPolicy = Literal["allow", "require_approval"]


class ScheduleExecutionEnvelope(BaseModel):
    """Validated schedule-owned run-envelope overrides."""

    side_effect_policy: ScheduleSideEffectPolicy | None = None

    model_config = ConfigDict(extra="allow")


class ScheduleExecutionParams(BaseModel):
    """Typed fields nested inside otherwise extensible execution params."""

    envelope: ScheduleExecutionEnvelope | None = None

    model_config = ConfigDict(extra="allow")


class AgentScheduleRunRead(BaseModel):
    id: UUID
    schedule_id: UUID
    scheduled_for: datetime
    status: str
    attempt_count: int
    conversation_id: UUID | None = None
    agent_run_id: UUID | None = None
    accepted_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    health: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_run(cls, run: AgentScheduleRun) -> "AgentScheduleRunRead":
        return cls.model_validate(
            {
                "id": run.id,
                "schedule_id": run.schedule_id,
                "scheduled_for": run.scheduled_for,
                "status": run.status,
                "attempt_count": run.attempt_count,
                "conversation_id": run.conversation_id,
                "agent_run_id": run.agent_run_id,
                "accepted_at": run.accepted_at,
                "completed_at": run.completed_at,
                "failed_at": run.failed_at,
                "last_error_code": run.last_error_code,
                "last_error_message": run.last_error_message,
                "created_at": run.created_at,
                "health": schedule_health_from_run(run),
            }
        )


class AgentScheduleRead(BaseModel):
    id: UUID
    agent_id: UUID
    user_id: UUID
    workspace_id: UUID
    name: str | None = None
    schedule_type: str
    cron_expression: str | None = None
    interval_minutes: int | None = None
    run_once_at: datetime | None = None
    timezone: str
    default_prompt: str | None = None
    execution_params: dict[str, Any] | None = None
    is_active: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    health: str | None = None
    latest_run: AgentScheduleRunRead | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_schedule(
        cls,
        schedule: AgentSchedule,
        *,
        latest_run: AgentScheduleRun | None = None,
    ) -> "AgentScheduleRead":
        return cls.model_validate(
            {
                "id": schedule.id,
                "agent_id": schedule.agent_id,
                "user_id": schedule.user_id,
                "workspace_id": schedule.workspace_id,
                "name": schedule.name,
                "schedule_type": schedule.schedule_type,
                "cron_expression": schedule.cron_expression,
                "interval_minutes": schedule.interval_minutes,
                "run_once_at": schedule.run_once_at,
                "timezone": schedule.timezone,
                "default_prompt": schedule.default_prompt,
                "execution_params": schedule.execution_params,
                "is_active": schedule.is_active,
                "last_run_at": schedule.last_run_at,
                "next_run_at": schedule.next_run_at if schedule.is_active else None,
                "created_at": schedule.created_at,
                "updated_at": schedule.updated_at,
                "health": schedule_health_from_run(latest_run),
                "latest_run": (
                    AgentScheduleRunRead.from_run(latest_run) if latest_run is not None else None
                ),
            }
        )


class AgentSchedulesListResponse(OffsetPage):
    items: list[AgentScheduleRead]


class AgentScheduleRunsListResponse(OffsetPage):
    items: list[AgentScheduleRunRead]


class AgentScheduleCreateRequest(BaseModel):
    agent_id: UUID
    name: str = Field(min_length=1, max_length=255)
    schedule_type: str = Field(max_length=32)
    cron_expression: str | None = Field(default=None, max_length=255)
    interval_minutes: int | None = None
    run_once_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    default_prompt: str = Field(max_length=20000)
    execution_params: dict[str, Any] | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("schedule_type")
    @classmethod
    def normalize_schedule_type(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("cron_expression", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("execution_params")
    @classmethod
    def validate_execution_params(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return validate_schedule_execution_params(value)


class AgentScheduleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    schedule_type: str | None = Field(default=None, max_length=32)
    cron_expression: str | None = Field(default=None, max_length=255)
    interval_minutes: int | None = None
    run_once_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    default_prompt: str | None = Field(default=None, max_length=20000)
    execution_params: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name_when_present(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("schedule_type")
    @classmethod
    def normalize_schedule_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("cron_expression", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @field_validator("execution_params")
    @classmethod
    def validate_execution_params(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return validate_schedule_execution_params(value)


class SchedulePreviewRequest(BaseModel):
    schedule_type: str = Field(max_length=32)
    cron_expression: str | None = Field(default=None, max_length=255)
    interval_minutes: int | None = None
    run_once_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    preview_count: int = Field(default=5, ge=1, le=20)

    @field_validator("schedule_type")
    @classmethod
    def normalize_schedule_type(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("cron_expression", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class SchedulePreviewResponse(BaseModel):
    next_runs: list[datetime]


def validate_schedule_execution_params(
    value: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    ScheduleExecutionParams.model_validate(value)
    return value


def schedule_side_effect_policy(
    value: object,
    *,
    default: str,
) -> str:
    """Return a valid persisted override or the configured default."""
    try:
        execution_params = ScheduleExecutionParams.model_validate(value or {})
    except ValidationError:
        return default
    if execution_params.envelope is None or execution_params.envelope.side_effect_policy is None:
        return default
    return execution_params.envelope.side_effect_policy
