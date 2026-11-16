# apps/api/services/integrations/microsoft_graph/time.py

"""Zone-explicit date and time values for Microsoft Graph calendar requests."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_TIME_ZONE_LENGTH = 64
# Every UTC offset in use falls between -12:00 and +14:00.
UTC_OFFSET_PADDING = (timedelta(hours=14), timedelta(hours=12))
_WINDOWS_ZONE = re.compile(r"(?:[A-Za-z][A-Za-z .\-]{0,48} Standard Time|UTC(?:[+-]\d{2})?)")


def parse_local_datetime(value: str, *, field: str) -> datetime:
    """Returns the naive date and time in ISO 8601 text that has no UTC offset.

    Raises:
        ValueError: If the text is not ISO 8601 or includes an offset.
    """
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(
            f"{field} must be an ISO 8601 date and time, such as 2026-11-16T09:00:00."
        ) from None
    if parsed.tzinfo is not None:
        raise ValueError(f"{field} must not include a UTC offset. Pass the zone as time_zone.")
    return parsed.replace(microsecond=0)


def validate_time_zone(value: str) -> str:
    """Returns the zone when it is an IANA name or a Windows zone name.

    Raises:
        ValueError: If the zone is neither.
    """
    zone = value.strip()
    if not 0 < len(zone) <= MAX_TIME_ZONE_LENGTH:
        raise ValueError("time_zone must be an IANA time zone, such as Europe/London.")
    if _WINDOWS_ZONE.fullmatch(zone):
        return zone
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(
            f"{zone} is not a known time zone. Use an IANA time zone, such as Europe/London."
        ) from None
    return zone


def bounded_window(start: str, end: str, *, max_days: int) -> tuple[datetime, datetime]:
    """Returns the parsed window after checking its order and length.

    Raises:
        ValueError: If the window is reversed, empty, or longer than its bound.
    """
    start_at = parse_local_datetime(start, field="start")
    end_at = parse_local_datetime(end, field="end")
    if end_at <= start_at:
        raise ValueError("end must be after start.")
    if end_at - start_at > timedelta(days=max_days):
        raise ValueError(f"The time window can be at most {max_days} days.")
    return start_at, end_at


def graph_date_time(value: datetime, time_zone: str) -> dict[str, str]:
    """Returns a Graph `dateTimeTimeZone` value."""
    return {"dateTime": value.isoformat(timespec="seconds"), "timeZone": time_zone}


def graph_local_datetime(value: object) -> datetime | None:
    """Returns the naive local time in a Graph `dateTimeTimeZone` value."""
    raw = value.get("dateTime") if isinstance(value, dict) else None
    if not isinstance(raw, str):
        return None
    # Graph sends seven fractional digits, which `fromisoformat` rejects.
    try:
        parsed = datetime.fromisoformat(raw[:19])
    except ValueError:
        return None
    return parsed if parsed.tzinfo is None else None
