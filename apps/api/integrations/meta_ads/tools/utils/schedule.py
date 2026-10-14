# apps/api/integrations/meta_ads/tools/utils/schedule.py

"""Turns schedule dates into Meta start and end times in the ad account's time zone."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import ModelRetry

from .validation import absolute_date


@dataclass(frozen=True, slots=True)
class Schedule:
    # None starts as soon as the object is turned on.
    start_time: str | None
    # None runs until turned off.
    end_time: str | None
    # Days the schedule covers, counting today when it has no start date; None without an end.
    days: int | None


def account_schedule(
    start_date: str | None,
    end_date: str | None,
    timezone_name: str | None,
    *,
    now: datetime | None = None,
) -> Schedule:
    """Starts at the start date's midnight and ends at the end date's last second, locally.

    Raises:
        ModelRetry: For a malformed or past date, an end before the start, or an
            account without a known time zone.
    """
    try:
        zone = ZoneInfo(timezone_name or "")
    except (ZoneInfoNotFoundError, ValueError):
        raise ModelRetry(
            "This ad account's time zone is unknown. Use Look for New Resources on the "
            "Meta Ads connection, then try again."
        ) from None
    today = (now or datetime.now(UTC)).astimezone(zone).date()
    start = absolute_date(start_date, "start_date") if start_date else None
    end = absolute_date(end_date, "end_date") if end_date else None
    if start is not None and start < today:
        raise ModelRetry(f"Set start_date to {today.isoformat()} or later.")
    if end is not None and end < (start or today):
        raise ModelRetry("Set end_date on or after start_date and today.")
    # A start today would be in the past by Meta's clock, so it starts on approval instead.
    start_time = _local(start, time.min, zone) if start is not None and start > today else None
    return Schedule(
        start_time=start_time,
        end_time=_local(end, time(23, 59, 59), zone) if end is not None else None,
        days=(end - (start or today)).days + 1 if end is not None else None,
    )


def _local(day: date, at: time, zone: ZoneInfo) -> str:
    return datetime.combine(day, at, tzinfo=zone).isoformat()
