# apps/api/utils/dates.py

"""Shared timezone-aware datetime helpers."""

from datetime import UTC, datetime

from core.exceptions.general import AppValidationError


def normalize_utc_datetime(value: datetime | None, *, field: str) -> datetime | None:
    """Normalize an aware datetime to UTC and reject naive values."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise AppValidationError("Datetime must include a timezone", field=field)
    return value.astimezone(UTC)
