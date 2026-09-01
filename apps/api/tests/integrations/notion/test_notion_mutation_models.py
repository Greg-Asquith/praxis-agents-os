"""Notion mutation input-model and property-encoding contracts."""

import pytest
from pydantic import TypeAdapter, ValidationError

from integrations.notion.operations.properties import encode_property_value
from integrations.notion.tools.mutations import (
    MAX_NOTION_PROPERTY_RECORDS,
    MAX_NOTION_REPLACEMENT_RECORDS,
    NotionPropertyRecord,
    NotionPropertyRecords,
    NotionReplacementRecord,
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
        ("url", " https://example.com ", "https://example.com", {"url": "https://example.com"}),
        ("email", " dana@example.com ", "dana@example.com", {"email": "dana@example.com"}),
        ("phone_number", " 800-555-0100 ", "800-555-0100", {"phone_number": "800-555-0100"}),
        (
            "date",
            " 2026-09-01T09:30:00+01:00..2026-09-02 ",
            "2026-09-01T09:30:00+01:00..2026-09-02",
            {
                "date": {
                    "start": "2026-09-01T09:30:00+01:00",
                    "end": "2026-09-02",
                }
            },
        ),
        ("select", " Planned ", "Planned", {"select": {"name": "Planned"}}),
        ("status", " In progress ", "In progress", {"status": {"name": "In progress"}}),
        (
            "multi_select",
            " API, Documentation ",
            "API, Documentation",
            {"multi_select": [{"name": "API"}, {"name": "Documentation"}]},
        ),
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


@pytest.mark.parametrize(
    ("property_type", "encoded"),
    [
        ("rich_text", {"rich_text": []}),
        ("number", {"number": None}),
        ("url", {"url": None}),
        ("email", {"email": None}),
        ("phone_number", {"phone_number": None}),
        ("date", {"date": None}),
        ("select", {"select": None}),
        ("status", {"status": None}),
        ("multi_select", {"multi_select": []}),
    ],
)
def test_empty_property_values_clear_every_type_except_title_and_checkbox(
    property_type: str,
    encoded: dict,
) -> None:
    record = NotionPropertyRecord(name="Field", type=property_type, value="  ")

    assert record.value == ""
    assert encode_property_value(record.type, record.value) == encoded


def test_title_property_cannot_be_cleared() -> None:
    with pytest.raises(ValidationError, match="Title properties cannot be cleared"):
        NotionPropertyRecord(name="Name", type="title", value=" ")


def test_checkbox_property_requires_an_explicit_boolean_value() -> None:
    with pytest.raises(ValidationError, match="use false instead"):
        NotionPropertyRecord(name="Complete", type="checkbox", value=" ")

    record = NotionPropertyRecord(name="Complete", type="checkbox", value=" FALSE ")
    assert record.value == "false"
    assert encode_property_value(record.type, record.value) == {"checkbox": False}


@pytest.mark.parametrize("property_type", ["email", "phone_number"])
def test_email_and_phone_values_enforce_notion_character_limits(property_type: str) -> None:
    value = "x" * 200

    record = NotionPropertyRecord(name="Contact", type=property_type, value=value)
    assert record.value == value
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name="Contact", type=property_type, value=f"{value}x")


def test_number_value_is_canonicalized_to_the_executed_json_number() -> None:
    record = NotionPropertyRecord(
        name="Ratio",
        type="number",
        value="0.12345678901234567890123456789",
    )

    assert record.value == "0.12345678901234568"
    assert encode_property_value(record.type, record.value) == {"number": 0.12345678901234568}


@pytest.mark.parametrize("value", ["2026-09-01", "2026-09-01T08:30:00Z"])
def test_date_property_accepts_bare_dates_and_offset_date_times(value: str) -> None:
    record = NotionPropertyRecord(name="Due", type="date", value=value)

    assert encode_property_value(record.type, record.value) == {
        "date": {"start": value, "end": None}
    }


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-01T09:30:00",
        "2026-02-30",
        "2026-09-01..",
        "2026-09-01..2026-09-02..2026-09-03",
    ],
)
def test_date_property_rejects_invalid_or_ambiguous_values(value: str) -> None:
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name="Due", type="date", value=value)


@pytest.mark.parametrize("replace_all", ["no", "yes", " NO ", " Yes "])
def test_replacement_record_accepts_and_normalizes_option_values(replace_all: str) -> None:
    record = NotionReplacementRecord(
        old_text="exact  text",
        new_text="replacement\ntext",
        replace_all=replace_all,
    )

    assert record.old_text == "exact  text"
    assert record.new_text == "replacement\ntext"
    assert record.replace_all == replace_all.strip().lower()


@pytest.mark.parametrize("replace_all", ["true", "false", "all", "", True])
def test_replacement_record_rejects_unknown_option_values(replace_all: object) -> None:
    with pytest.raises(ValidationError):
        NotionReplacementRecord(old_text="old", new_text="new", replace_all=replace_all)


def test_mutation_records_reject_unknown_keys_and_non_string_cells() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NotionPropertyRecord(name="Priority", type="select", value="High", extra="value")
    with pytest.raises(ValidationError):
        NotionReplacementRecord(old_text="old", new_text=1, replace_all="no")


@pytest.mark.parametrize(
    ("model", "required"),
    [
        (NotionPropertyRecord, {"name", "type", "value"}),
        (NotionReplacementRecord, {"old_text", "new_text", "replace_all"}),
    ],
)
def test_mutation_record_schemas_expose_only_required_string_cells(
    model, required: set[str]
) -> None:
    schema = model.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == required
    assert set(schema["properties"]) == required
    for field in schema["properties"].values():
        if reference := field.get("$ref"):
            field = schema["$defs"][reference.rsplit("/", maxsplit=1)[-1]]
        assert field["type"] == "string"


def test_mutation_records_reject_empty_required_text_and_oversized_names() -> None:
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name=" ", type="rich_text", value="Summary")
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name="n" * 256, type="rich_text", value="Summary")
    with pytest.raises(ValidationError):
        NotionReplacementRecord(old_text="", new_text="replacement", replace_all="no")


def test_property_record_bounds_count_unicode_characters_and_require_valid_utf8() -> None:
    value = "\U0001f680" * 2_000
    record = NotionPropertyRecord(name="\U0001f680" * 255, type="rich_text", value=value)

    assert record.value == value
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name="Name", type="rich_text", value=f"{value}\U0001f680")
    with pytest.raises(ValidationError, match="valid Unicode text"):
        NotionPropertyRecord(name="Name", type="rich_text", value="\ud800")


def test_replacement_record_enforces_character_and_utf8_bounds() -> None:
    text = "\U0001f680" * 4_000
    record = NotionReplacementRecord(old_text=text, new_text=text, replace_all="yes")

    assert record.old_text == text
    with pytest.raises(ValidationError):
        NotionReplacementRecord(old_text=f"{text}\U0001f680", new_text="", replace_all="no")
    with pytest.raises(ValidationError, match="valid Unicode text"):
        NotionReplacementRecord(old_text="old", new_text="\ud800", replace_all="no")


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


def test_record_lists_enforce_provider_operation_limits() -> None:
    properties = [
        {"name": f"Field {index}", "type": "number", "value": str(index)}
        for index in range(MAX_NOTION_PROPERTY_RECORDS + 1)
    ]
    replacements = [
        {"old_text": f"old {index}", "new_text": f"new {index}", "replace_all": "no"}
        for index in range(MAX_NOTION_REPLACEMENT_RECORDS + 1)
    ]

    with pytest.raises(ValidationError):
        TypeAdapter(NotionPropertyRecords).validate_python(properties)
    with pytest.raises(ValidationError):
        TypeAdapter(NotionReplacementRecords).validate_python(replacements)
    with pytest.raises(ValidationError):
        TypeAdapter(NotionReplacementRecords).validate_python([])


@pytest.mark.parametrize(
    ("property_type", "value"),
    [
        ("number", "not-a-number"),
        ("number", "NaN"),
        ("checkbox", "yes"),
        ("select", "High, urgent"),
        ("multi_select", "API,,Documentation"),
        ("multi_select", "API,API"),
        ("multi_select", ",".join(f"Option {index}" for index in range(101))),
    ],
)
def test_property_records_reject_invalid_typed_values(property_type: str, value: str) -> None:
    with pytest.raises(ValidationError):
        NotionPropertyRecord(name="Field", type=property_type, value=value)
