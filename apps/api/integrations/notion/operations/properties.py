# apps/api/integrations/notion/operations/properties.py

"""Notion mutation property parsing and provider encoding."""

import math
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from integrations.notion.operations.utils import (
    MAX_EMAIL_CHARS,
    MAX_MULTI_SELECT_VALUES,
    MAX_PHONE_NUMBER_CHARS,
    MAX_RICH_TEXT_CHARS,
)

MAX_NOTION_PROPERTY_NAME_CHARS = 255
MAX_NOTION_PROPERTY_NAME_BYTES = MAX_NOTION_PROPERTY_NAME_CHARS * 4
MAX_NOTION_PROPERTY_VALUE_BYTES = MAX_RICH_TEXT_CHARS * 4

type NotionWritablePropertyType = Literal[
    "title",
    "rich_text",
    "number",
    "checkbox",
    "url",
    "email",
    "phone_number",
    "date",
    "select",
    "status",
    "multi_select",
]


def normalize_property_name(value: str) -> str:
    """Returns a bounded property name with normalized whitespace."""
    normalized = " ".join(value.split())
    _validate_text_bound(
        normalized,
        field_name="Property name",
        min_chars=1,
        max_chars=MAX_NOTION_PROPERTY_NAME_CHARS,
        max_bytes=MAX_NOTION_PROPERTY_NAME_BYTES,
    )
    return normalized


def normalize_property_value(property_type: NotionWritablePropertyType, value: str) -> str:
    """Returns a canonical property value after type-specific validation."""
    normalized = value.strip()
    _validate_text_bound(
        normalized,
        field_name="Property value",
        min_chars=0,
        max_chars=MAX_RICH_TEXT_CHARS,
        max_bytes=MAX_NOTION_PROPERTY_VALUE_BYTES,
    )
    if not normalized:
        return _empty_property_value(property_type)
    normalizer = _PROPERTY_VALUE_NORMALIZERS.get(property_type)
    return normalizer(normalized) if normalizer is not None else normalized


def encode_property_value(
    property_type: NotionWritablePropertyType,
    value: str,
) -> dict[str, Any]:
    """Returns a Notion property-value object for a validated scalar value."""
    normalized = normalize_property_value(property_type, value)
    if property_type in {"title", "rich_text"}:
        encoded: Any = [{"type": "text", "text": {"content": normalized}}] if normalized else []
    elif property_type == "number":
        encoded = _decimal_value(normalized) if normalized else None
    elif property_type == "checkbox":
        encoded = normalized == "true" if normalized else None
    elif property_type in {"url", "email", "phone_number"}:
        encoded = normalized or None
    elif property_type == "date":
        encoded = _date_value(normalized) if normalized else None
    elif property_type in {"select", "status"}:
        encoded = {"name": normalized} if normalized else None
    else:
        encoded = [{"name": item} for item in _multi_select_values(normalized)]
    return {property_type: encoded}


def validate_utf8_text(
    value: str,
    *,
    field_name: str,
    min_chars: int,
    max_chars: int,
    max_bytes: int,
) -> str:
    """Returns text that satisfies character and UTF-8 byte bounds."""
    _validate_text_bound(
        value,
        field_name=field_name,
        min_chars=min_chars,
        max_chars=max_chars,
        max_bytes=max_bytes,
    )
    return value


def _validate_text_bound(
    value: str,
    *,
    field_name: str,
    min_chars: int,
    max_chars: int,
    max_bytes: int,
) -> None:
    if not min_chars <= len(value) <= max_chars:
        raise ValueError(
            f"{field_name} must contain between {min_chars} and {max_chars} characters"
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must contain valid Unicode text") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"{field_name} exceeds the {max_bytes}-byte limit")


def _decimal_value(value: str) -> int | float:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Number values must be decimal strings") from exc
    if not parsed.is_finite():
        raise ValueError("Number values must be finite")
    if parsed == parsed.to_integral_value():
        return int(parsed)
    encoded = float(parsed)
    if not math.isfinite(encoded):
        raise ValueError("Number values must fit in a finite JSON number")
    return encoded


def _empty_property_value(property_type: NotionWritablePropertyType) -> str:
    if property_type == "title":
        raise ValueError("Title properties cannot be cleared")
    if property_type == "checkbox":
        raise ValueError("Checkbox properties cannot be cleared; use false instead")
    return ""


def _normalize_number(value: str) -> str:
    return str(_decimal_value(value))


def _normalize_checkbox(value: str) -> str:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise ValueError("Checkbox values must be true or false")
    return normalized


def _normalize_email(value: str) -> str:
    return _bounded_property_text(value, field_name="Email value", max_chars=MAX_EMAIL_CHARS)


def _normalize_phone_number(value: str) -> str:
    return _bounded_property_text(
        value,
        field_name="Phone number value",
        max_chars=MAX_PHONE_NUMBER_CHARS,
    )


def _bounded_property_text(value: str, *, field_name: str, max_chars: int) -> str:
    _validate_text_bound(
        value,
        field_name=field_name,
        min_chars=1,
        max_chars=max_chars,
        max_bytes=max_chars * 4,
    )
    return value


def _normalize_date(value: str) -> str:
    _date_value(value)
    return value


def _normalize_select(value: str) -> str:
    if "," in value:
        raise ValueError("Select values cannot contain commas")
    return value


def _normalize_multi_select(value: str) -> str:
    return ", ".join(_multi_select_values(value))


def _date_value(value: str) -> dict[str, str | None]:
    parts = value.split("..")
    if len(parts) > 2 or any(not part for part in parts):
        raise ValueError("Date values must contain one date or a start and end separated by ..")
    for part in parts:
        _validate_iso_date_or_datetime(part)
    return {
        "start": parts[0],
        "end": parts[1] if len(parts) == 2 else None,
    }


def _validate_iso_date_or_datetime(value: str) -> None:
    if "T" not in value:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Date values must use ISO 8601 format") from exc
        if parsed_date.isoformat() != value:
            raise ValueError("Date values must use ISO 8601 format")
        return
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed_datetime = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("Date-time values must use ISO 8601 format") from exc
    if parsed_datetime.tzinfo is None or parsed_datetime.utcoffset() is None:
        raise ValueError("Date-time values must include a UTC offset")


def _multi_select_values(value: str) -> list[str]:
    if not value:
        return []
    items = [item.strip() for item in value.split(",")]
    if any(not item for item in items):
        raise ValueError("Multi-select values cannot contain empty option names")
    if len(items) > MAX_MULTI_SELECT_VALUES:
        raise ValueError(
            f"Multi-select values cannot contain more than {MAX_MULTI_SELECT_VALUES} options"
        )
    if len(items) != len(set(items)):
        raise ValueError("Multi-select values cannot contain duplicate option names")
    return items


_PROPERTY_VALUE_NORMALIZERS: dict[str, Callable[[str], str]] = {
    "number": _normalize_number,
    "checkbox": _normalize_checkbox,
    "email": _normalize_email,
    "phone_number": _normalize_phone_number,
    "date": _normalize_date,
    "select": _normalize_select,
    "multi_select": _normalize_multi_select,
}
