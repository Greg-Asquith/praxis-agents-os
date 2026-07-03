# apps/api/services/agent_schedules/schemas.py

"""Pydantic contracts for agent schedule routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.agent import AgentSchedule, AgentScheduleRun
from services.agent_schedules.runs import schedule_health_from_run


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
                    AgentScheduleRunRead.from_run(latest_run)
                    if latest_run is not None
                    else None
                ),
            }
        )


class AgentSchedulesListResponse(BaseModel):
    items: list[AgentScheduleRead]
    total: int
    limit: int
    offset: int


class AgentScheduleRunsListResponse(BaseModel):
    items: list[AgentScheduleRunRead]
    total: int
    limit: int
    offset: int


class AgentScheduleCreateRequest(BaseModel):
    agent_id: UUID
    schedule_type: str = Field(max_length=32)
    cron_expression: str | None = Field(default=None, max_length=255)
    interval_minutes: int | None = None
    run_once_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    default_prompt: str = Field(max_length=20000)
    execution_params: dict[str, Any] | None = None
    is_active: bool = True

    @field_validator("schedule_type")
    @classmethod
    def normalize_schedule_type(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("cron_expression", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


class AgentScheduleUpdateRequest(BaseModel):
    schedule_type: str | None = Field(default=None, max_length=32)
    cron_expression: str | None = Field(default=None, max_length=255)
    interval_minutes: int | None = None
    run_once_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    default_prompt: str | None = Field(default=None, max_length=20000)
    execution_params: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("schedule_type")
    @classmethod
    def normalize_schedule_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("cron_expression", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


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
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


class SchedulePreviewResponse(BaseModel):
    next_runs: list[datetime]
