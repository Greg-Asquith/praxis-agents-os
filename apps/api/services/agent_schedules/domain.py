# apps/api/services/agent_schedules/domain.py

"""Schedule validation and next-run calculation helpers."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from core.exceptions.general import AppValidationError
from utils.dates import normalize_utc_datetime

VALID_SCHEDULE_TYPES = frozenset({"cron", "interval", "once"})
DEFAULT_TIMEZONE = "UTC"
# Upper bound on preview iterations to avoid unbounded croniter loops in-request.
_MAX_PREVIEW_COUNT = 100
_TIMING_FIELDS_BY_TYPE = {
    "cron": frozenset({"cron_expression"}),
    "interval": frozenset({"interval_minutes"}),
    "once": frozenset({"run_once_at"}),
}


@dataclass(frozen=True)
class ScheduleConfig:
    """Normalized persisted schedule timing fields."""

    schedule_type: str
    cron_expression: str | None
    interval_minutes: int | None
    run_once_at: datetime | None
    timezone: str = DEFAULT_TIMEZONE


def _resolve_timezone(timezone: str | None) -> ZoneInfo:
    """Validate an IANA zone name, returning its ZoneInfo."""

    name = timezone or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppValidationError(f"Invalid timezone '{name}'", field="timezone") from exc


def normalize_schedule_config(
    *,
    schedule_type: str,
    cron_expression: str | None,
    interval_minutes: int | None,
    run_once_at: datetime | None,
    timezone: str | None = None,
    now: datetime | None = None,
    require_future_once: bool = True,
    supplied_fields: set[str] | frozenset[str] | None = None,
) -> ScheduleConfig:
    """Validate schedule timing fields and clear incompatible persisted fields."""

    if schedule_type not in VALID_SCHEDULE_TYPES:
        valid_types = ", ".join(sorted(VALID_SCHEDULE_TYPES))
        raise AppValidationError(
            f"Invalid schedule type '{schedule_type}'. Must be one of: {valid_types}",
            field="schedule_type",
        )

    _resolve_timezone(timezone)
    normalized_timezone = timezone or DEFAULT_TIMEZONE

    if supplied_fields is not None:
        timing_values = {
            "cron_expression": cron_expression,
            "interval_minutes": interval_minutes,
            "run_once_at": run_once_at,
        }
        allowed_fields = _TIMING_FIELDS_BY_TYPE[schedule_type]
        for field_name, field_value in timing_values.items():
            if field_name in allowed_fields:
                continue
            if field_name in supplied_fields and field_value is not None:
                raise AppValidationError(
                    f"{field_name} cannot be set for {schedule_type} schedules",
                    field=field_name,
                )

    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)
    run_once_at_utc = normalize_utc_datetime(run_once_at, field="run_once_at")

    if schedule_type == "cron":
        if not cron_expression:
            raise AppValidationError(
                "Cron expression is required for cron schedules",
                field="cron_expression",
            )
        try:
            croniter(cron_expression, now_utc)
        except Exception as exc:
            raise AppValidationError(
                f"Invalid cron expression: {exc}", field="cron_expression"
            ) from exc
        return ScheduleConfig(
            schedule_type="cron",
            cron_expression=cron_expression,
            interval_minutes=None,
            run_once_at=None,
            timezone=normalized_timezone,
        )

    if schedule_type == "interval":
        if interval_minutes is None:
            raise AppValidationError(
                "Interval minutes is required for interval schedules",
                field="interval_minutes",
            )
        if interval_minutes < 1:
            raise AppValidationError(
                "Interval minutes must be greater than or equal to 1",
                field="interval_minutes",
            )
        return ScheduleConfig(
            schedule_type="interval",
            cron_expression=None,
            interval_minutes=interval_minutes,
            run_once_at=None,
            timezone=normalized_timezone,
        )

    if run_once_at_utc is None:
        raise AppValidationError(
            "Run once time is required for once schedules", field="run_once_at"
        )
    if require_future_once and run_once_at_utc <= now_utc:
        raise AppValidationError("Run once time must be in the future", field="run_once_at")
    return ScheduleConfig(
        schedule_type="once",
        cron_expression=None,
        interval_minutes=None,
        run_once_at=run_once_at_utc,
        timezone=normalized_timezone,
    )


def calculate_next_run(
    config: ScheduleConfig,
    *,
    basis: datetime | None = None,
    repeat_once: bool = True,
) -> datetime | None:
    """Calculate the next due time for a normalized schedule config."""

    basis_utc = normalize_utc_datetime(basis, field="basis") or datetime.now(UTC)

    if config.schedule_type == "once":
        return config.run_once_at if repeat_once else None

    if config.schedule_type == "interval":
        if config.interval_minutes is None:
            return None
        return basis_utc + timedelta(minutes=config.interval_minutes)

    if config.schedule_type == "cron":
        if not config.cron_expression:
            return None
        # Evaluate cron in its own zone so wall-clock times survive DST, then return UTC.
        zone = _resolve_timezone(config.timezone)
        local_next = croniter(config.cron_expression, basis_utc.astimezone(zone)).get_next(datetime)
        return local_next.astimezone(UTC)

    return None


def preview_schedule_runs(
    config: ScheduleConfig,
    *,
    preview_count: int,
    basis: datetime | None = None,
) -> list[datetime]:
    """Return upcoming schedule runs from one canonical calculation path."""

    if preview_count < 1:
        raise AppValidationError("Preview count must be at least 1", field="preview_count")
    if preview_count > _MAX_PREVIEW_COUNT:
        raise AppValidationError(
            f"Preview count must not exceed {_MAX_PREVIEW_COUNT}", field="preview_count"
        )

    if config.schedule_type == "once":
        next_run = calculate_next_run(config, basis=basis, repeat_once=True)
        return [next_run] if next_run is not None else []

    upcoming_runs: list[datetime] = []
    next_basis = normalize_utc_datetime(basis, field="basis") or datetime.now(UTC)

    for _ in range(preview_count):
        next_run = calculate_next_run(config, basis=next_basis, repeat_once=True)
        if next_run is None:
            break
        upcoming_runs.append(next_run)
        next_basis = next_run

    return upcoming_runs
