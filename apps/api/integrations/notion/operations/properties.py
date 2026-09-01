# apps/api/integrations/notion/operations/properties.py

"""Notion mutation property parsing and provider encoding."""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol
from urllib.parse import quote

from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from integrations.notion.operations.utils import (
    MAX_EMAIL_CHARS,
    MAX_MULTI_SELECT_VALUES,
    MAX_PHONE_NUMBER_CHARS,
    MAX_RICH_TEXT_CHARS,
    data_source_title,
    notion_id,
    page_title,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from ..references import NotionDataSourceReference, NotionPageReference

MAX_NOTION_PROPERTY_NAME_CHARS = 255
MAX_NOTION_PROPERTY_NAME_BYTES = MAX_NOTION_PROPERTY_NAME_CHARS * 4
MAX_NOTION_PROPERTY_VALUE_BYTES = MAX_RICH_TEXT_CHARS * 4
READ_ONLY_NOTION_PROPERTY_TYPES = frozenset(
    {
        "formula",
        "rollup",
        "created_time",
        "created_by",
        "last_edited_time",
        "last_edited_by",
        "unique_id",
        "verification",
        "button",
        "relation",
        "people",
        "files",
    }
)

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
NOTION_WRITABLE_PROPERTY_TYPES: tuple[NotionWritablePropertyType, ...] = (
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
)


class NotionPropertyRecordLike(Protocol):
    """Describes one normalized property record accepted by mutation preparation."""

    name: str
    type: NotionWritablePropertyType
    value: str


@dataclass(frozen=True)
class NotionMutationTarget:
    """Carries live provider state used to validate a Notion mutation."""

    entity_type: Literal["notion_page", "notion_data_source"]
    external_id: str
    display_name: str
    property_types: Mapping[str, str]
    property_options: Mapping[str, frozenset[str]] = field(default_factory=dict)
    parent_data_source_id: str | None = None


async def get_page_mutation_target(
    client: NotionClient,
    reference: NotionPageReference,
) -> NotionMutationTarget:
    """Gets and validates the live page state required before a mutation."""
    return await _get_mutation_target(
        client,
        path=f"pages/{_quoted_id(reference.page_id)}",
        operation="prepare_page_mutation",
        entity_type="notion_page",
        expected_id=reference.page_id,
    )


async def get_data_source_mutation_target(
    client: NotionClient,
    reference: NotionDataSourceReference,
) -> NotionMutationTarget:
    """Gets and validates the live data-source state required before a mutation."""
    return await _get_mutation_target(
        client,
        path=f"data_sources/{_quoted_id(reference.data_source_id)}",
        operation="prepare_data_source_mutation",
        entity_type="notion_data_source",
        expected_id=reference.data_source_id,
    )


def validate_property_records_against_schema(
    records: Sequence[NotionPropertyRecordLike],
    target: NotionMutationTarget,
    *,
    reserved_property_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Returns provider values after validating records against the live schema."""
    encoded: dict[str, dict[str, Any]] = {}
    for record in records:
        live_type = target.property_types.get(record.name)
        if live_type is None:
            raise ModelRetry(
                f"Notion property {record.name!r} is no longer available. "
                "Choose a property from the current schema."
            )
        if live_type in READ_ONLY_NOTION_PROPERTY_TYPES:
            raise ModelRetry(f"Notion property {record.name!r} is read-only.")
        if live_type != record.type:
            raise ModelRetry(
                f"Notion property {record.name!r} now has type {live_type!r}, not {record.type!r}."
            )
        if reserved_property_name is not None and record.name == reserved_property_name:
            raise ModelRetry(
                f"Set the page title with the title argument, not property {record.name!r}."
            )
        _validate_property_options(record, target)
        encoded[record.name] = encode_property_value(record.type, record.value)
    return encoded


def _validate_property_options(
    record: NotionPropertyRecordLike,
    target: NotionMutationTarget,
) -> None:
    if record.type not in {"select", "status", "multi_select"} or not record.value:
        return
    options = target.property_options.get(record.name)
    if options is None:
        raise IntegrationValidationError(
            "Notion returned an incomplete option schema",
            provider_key="notion",
            operation="prepare_data_source_mutation",
        )
    requested = (
        {record.value}
        if record.type in {"select", "status"}
        else set(_multi_select_values(record.value))
    )
    unknown = sorted(requested - options)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise ModelRetry(
            f"Notion property {record.name!r} does not contain option {names}. "
            "Choose an option from the current schema."
        )


def validate_mutation_scope(
    entry: ResolvedContextEntry,
    provider_scope_id: str,
    *,
    reference_label: str,
) -> None:
    """Rejects a mutation reference outside the selected Notion workspace."""
    if provider_scope_id != entry.external_id:
        raise ModelRetry(
            f"The selected Notion {reference_label} is no longer in the active integration "
            f"context. Choose the {reference_label} again."
        )


def data_source_title_property(target: NotionMutationTarget) -> str:
    """Returns the single title property declared by a live data source."""
    title_names = [
        name for name, property_type in target.property_types.items() if property_type == "title"
    ]
    if len(title_names) != 1:
        raise IntegrationValidationError(
            "Notion returned a data source without one title property",
            provider_key="notion",
            operation="prepare_data_source_mutation",
        )
    return title_names[0]


async def _get_mutation_target(
    client: NotionClient,
    *,
    path: str,
    operation: str,
    entity_type: Literal["notion_page", "notion_data_source"],
    expected_id: str,
) -> NotionMutationTarget:
    payload = await client.get(path, operation=operation, policy=IntegrationRequestPolicy.READ)
    expected_object = "page" if entity_type == "notion_page" else "data_source"
    if (
        not isinstance(payload, Mapping)
        or payload.get("object") != expected_object
        or notion_id(payload) != expected_id
    ):
        raise IntegrationValidationError(
            "Notion returned an invalid mutation target",
            provider_key="notion",
            operation=operation,
        )
    in_trash = payload.get("in_trash")
    if not isinstance(in_trash, bool):
        raise IntegrationValidationError(
            "Notion returned an invalid trash status",
            provider_key="notion",
            operation=operation,
        )
    if in_trash:
        raise ModelRetry("The selected Notion resource is in the trash. Choose another resource.")
    raw_properties = payload.get("properties")
    if not isinstance(raw_properties, Mapping):
        raise IntegrationValidationError(
            "Notion returned an invalid property schema",
            provider_key="notion",
            operation=operation,
        )
    property_types: dict[str, str] = {}
    property_options: dict[str, frozenset[str]] = {}
    for raw_name, raw_property in raw_properties.items():
        if not isinstance(raw_name, str) or not raw_name or not isinstance(raw_property, Mapping):
            raise IntegrationValidationError(
                "Notion returned an invalid property schema",
                provider_key="notion",
                operation=operation,
            )
        property_type = raw_property.get("type")
        if not isinstance(property_type, str) or not property_type:
            raise IntegrationValidationError(
                "Notion returned an invalid property schema",
                provider_key="notion",
                operation=operation,
            )
        property_types[raw_name] = property_type
        if entity_type == "notion_data_source" and property_type in {
            "select",
            "status",
            "multi_select",
        }:
            property_options[raw_name] = _property_option_names(
                raw_property,
                property_type=property_type,
                operation=operation,
            )
    title = page_title(payload) if entity_type == "notion_page" else data_source_title(payload)
    return NotionMutationTarget(
        entity_type=entity_type,
        external_id=expected_id,
        display_name=(title or "(untitled)")[:500],
        property_types=property_types,
        property_options=property_options,
        parent_data_source_id=(
            _page_parent_data_source_id(payload) if entity_type == "notion_page" else None
        ),
    )


def _property_option_names(
    raw_property: Mapping[str, Any],
    *,
    property_type: str,
    operation: str,
) -> frozenset[str]:
    configuration = raw_property.get(property_type)
    raw_options = configuration.get("options") if isinstance(configuration, Mapping) else None
    if not isinstance(raw_options, Sequence) or isinstance(raw_options, (str, bytes)):
        raise IntegrationValidationError(
            "Notion returned an invalid property option schema",
            provider_key="notion",
            operation=operation,
        )
    names: list[str] = []
    for option in raw_options:
        name = option.get("name") if isinstance(option, Mapping) else None
        if not isinstance(name, str) or not name or name in names:
            raise IntegrationValidationError(
                "Notion returned an invalid property option schema",
                provider_key="notion",
                operation=operation,
            )
        names.append(name)
    return frozenset(names)


def _page_parent_data_source_id(payload: Mapping[str, Any]) -> str | None:
    parent = payload.get("parent")
    if not isinstance(parent, Mapping) or parent.get("type") != "data_source_id":
        return None
    data_source_id = parent.get("data_source_id")
    return data_source_id if isinstance(data_source_id, str) and data_source_id else None


def _quoted_id(value: str) -> str:
    return quote(value, safe="")


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
