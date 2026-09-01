# apps/api/integrations/notion/tools/mutations.py

"""Strict input contracts shared by Notion mutation tools."""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from integrations.notion.operations.properties import (
    NotionWritablePropertyType,
    encode_property_value,
    normalize_property_name,
    normalize_property_value,
    validate_utf8_text,
)
from integrations.notion.operations.utils import validate_mutation_body_size

MAX_NOTION_PROPERTY_RECORDS = 50
MAX_NOTION_REPLACEMENT_RECORDS = 20
MAX_NOTION_REPLACEMENT_TEXT_CHARS = 4_000
MAX_NOTION_REPLACEMENT_TEXT_BYTES = MAX_NOTION_REPLACEMENT_TEXT_CHARS * 4


class _StrictMutationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NotionPropertyRecord(_StrictMutationModel):
    name: str
    type: NotionWritablePropertyType
    value: str

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_property_name(value)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_value(self) -> "NotionPropertyRecord":
        self.value = normalize_property_value(self.type, self.value)
        return self


class NotionReplacementRecord(_StrictMutationModel):
    old_text: str
    new_text: str
    replace_all: Literal["no", "yes"]

    @field_validator("old_text")
    @classmethod
    def validate_old_text(cls, value: str) -> str:
        return validate_utf8_text(
            value,
            field_name="Find text",
            min_chars=1,
            max_chars=MAX_NOTION_REPLACEMENT_TEXT_CHARS,
            max_bytes=MAX_NOTION_REPLACEMENT_TEXT_BYTES,
        )

    @field_validator("new_text")
    @classmethod
    def validate_new_text(cls, value: str) -> str:
        return validate_utf8_text(
            value,
            field_name="Replacement text",
            min_chars=0,
            max_chars=MAX_NOTION_REPLACEMENT_TEXT_CHARS,
            max_bytes=MAX_NOTION_REPLACEMENT_TEXT_BYTES,
        )

    @field_validator("replace_all", mode="before")
    @classmethod
    def normalize_replace_all(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


def _validate_property_records(
    records: list[NotionPropertyRecord],
) -> list[NotionPropertyRecord]:
    names = [record.name for record in records]
    if len(names) != len(set(names)):
        raise ValueError("Property records cannot contain duplicate names")
    payload = {
        "properties": {
            record.name: encode_property_value(record.type, record.value) for record in records
        }
    }
    validate_mutation_body_size(payload)
    return records


def _validate_replacement_records(
    records: list[NotionReplacementRecord],
) -> list[NotionReplacementRecord]:
    payload = {
        "update_content": {
            "content_updates": [
                {
                    "old_str": record.old_text,
                    "new_str": record.new_text,
                    "replace_all_matches": record.replace_all == "yes",
                }
                for record in records
            ]
        }
    }
    validate_mutation_body_size(payload)
    return records


type NotionPropertyRecords = Annotated[
    list[NotionPropertyRecord],
    Field(max_length=MAX_NOTION_PROPERTY_RECORDS),
    AfterValidator(_validate_property_records),
]

type NotionPropertyUpdateRecords = Annotated[
    list[NotionPropertyRecord],
    Field(min_length=1, max_length=MAX_NOTION_PROPERTY_RECORDS),
    AfterValidator(_validate_property_records),
]

type NotionReplacementRecords = Annotated[
    list[NotionReplacementRecord],
    Field(min_length=1, max_length=MAX_NOTION_REPLACEMENT_RECORDS),
    AfterValidator(_validate_replacement_records),
]
