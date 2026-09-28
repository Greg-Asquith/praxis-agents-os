"""Notion mutation input-model and property-encoding contracts."""

import pytest
from pydantic import TypeAdapter, ValidationError

from integrations.notion.operations.properties import encode_property_value
from integrations.notion.tools.mutations import (
    NotionPropertyRecord,
    NotionPropertyRecords,
    NotionReplacementRecords,
)


@pytest.mark.parametrize(
    ("property_type", "value", "normalized", "encoded"),
    [
        (
            "title",
            " Launch plan ",
            "Launch plan",
            {"title": [{"type": "text", "text": {"content": "Launch plan"}}]},
        ),
        (
            "rich_text",
            " Summary ",
            "Summary",
            {"rich_text": [{"type": "text", "text": {"content": "Summary"}}]},
        ),
        ("number", " 12.50 ", "12.5", {"number": 12.5}),
        ("checkbox", " TRUE ", "true", {"checkbox": True}),
    ],
)
def test_property_records_parse_and_encode_every_writable_type(
    property_type: str,
    value: str,
    normalized: str,
    encoded: dict,
) -> None:
    record = NotionPropertyRecord(name=" Delivery   status ", type=property_type, value=value)

    assert record.name == "Delivery status"
    assert record.value == normalized
    assert encode_property_value(record.type, record.value) == encoded


def test_title_property_cannot_be_cleared() -> None:
    with pytest.raises(ValidationError, match="Title properties cannot be cleared"):
        NotionPropertyRecord(name="Name", type="title", value=" ")


def test_number_value_is_canonicalized_to_the_executed_json_number() -> None:
    record = NotionPropertyRecord(
        name="Ratio",
        type="number",
        value="0.12345678901234567890123456789",
    )

    assert record.value == "0.12345678901234568"
    assert encode_property_value(record.type, record.value) == {"number": 0.12345678901234568}


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-01T09:30:00",
        "2026-02-30",
    ],
)
def test_date_property_rejects_invalid_or_ambiguous_values(value: str) -> None:
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name="Due", type="date", value=value)


def test_replacement_record_list_enforces_provider_request_byte_limit() -> None:
    record = {
        "old_text": "\U0001f680" * 4_000,
        "new_text": "\U0001f680" * 4_000,
        "replace_all": "yes",
    }

    TypeAdapter(NotionReplacementRecords).validate_python([record] * 15)
    with pytest.raises(ValidationError, match="500000-byte limit"):
        TypeAdapter(NotionReplacementRecords).validate_python([record] * 16)


def test_property_record_list_rejects_duplicates_after_normalization() -> None:
    adapter = TypeAdapter(NotionPropertyRecords)

    with pytest.raises(ValidationError, match="duplicate names"):
        adapter.validate_python(
            [
                {"name": "Delivery status", "type": "status", "value": "Planned"},
                {"name": "Delivery   status", "type": "status", "value": "Done"},
            ]
        )


@pytest.mark.parametrize(
    ("property_type", "value"),
    [
        ("number", "not-a-number"),
        ("number", "NaN"),
        ("checkbox", "yes"),
    ],
)
def test_property_records_reject_invalid_typed_values(property_type: str, value: str) -> None:
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name="Field", type=property_type, value=value)
