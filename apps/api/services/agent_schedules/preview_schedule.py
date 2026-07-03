# apps/api/services/agent_schedules/preview_schedule.py

"""Preview upcoming schedule fire times."""

from services.agent_schedules.domain import normalize_schedule_config, preview_schedule_runs
from services.agent_schedules.schemas import SchedulePreviewRequest, SchedulePreviewResponse


async def preview_schedule(payload: SchedulePreviewRequest) -> SchedulePreviewResponse:
    config = normalize_schedule_config(
        schedule_type=payload.schedule_type,
        cron_expression=payload.cron_expression,
        interval_minutes=payload.interval_minutes,
        run_once_at=payload.run_once_at,
        timezone=payload.timezone,
        require_future_once=False,
        supplied_fields={
            "schedule_type",
            "cron_expression",
            "interval_minutes",
            "run_once_at",
            "timezone",
        },
    )
    return SchedulePreviewResponse(
        next_runs=preview_schedule_runs(
            config,
            preview_count=payload.preview_count,
        )
    )
