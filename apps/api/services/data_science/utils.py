# apps/api/services/data_science/utils.py

"""Helpers for the data science services."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from services.data_science.domain import Frequency

MAX_DECIMALS = 6


def period_labels(start: str, frequency: Frequency, count: int) -> list[str]:
    """Returns each period's ISO start: a date and hour for hourly, otherwise a date."""
    first = datetime.fromisoformat(start)
    if frequency == "hourly":
        return [
            (first + timedelta(hours=index)).isoformat(timespec="seconds") for index in range(count)
        ]
    if frequency in {"daily", "weekly"}:
        step = 1 if frequency == "daily" else 7
        return [(first + timedelta(days=step * index)).date().isoformat() for index in range(count)]
    labels = []
    for index in range(count):
        year, month = divmod(first.month - 1 + index, 12)
        labels.append(f"{first.year + year:04d}-{month + 1:02d}-01")
    return labels


def input_decimals(values: Sequence[float | None]) -> int:
    """Returns the most decimal places any value was given with, up to six."""
    decimals = 0
    for value in values:
        if value is None or float(value).is_integer():
            continue
        text = repr(float(value))
        if "e" in text:
            return MAX_DECIMALS
        decimals = max(decimals, len(text.split(".")[1]))
    return min(decimals, MAX_DECIMALS)
