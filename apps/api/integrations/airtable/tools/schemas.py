# apps/api/integrations/airtable/tools/schemas.py

"""Typed Airtable tool-result contracts with dynamic values confined to fields."""

from pydantic import BaseModel, ConfigDict, Field

from integrations.airtable.references import AirtableRecordReference
from services.agents.runtime.untrusted import UntrustedJsonValue
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)


class AirtableRecordData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    reference: AirtableRecordReference | None = None
    created_time: str | None = None
    fields: dict[str, UntrustedJsonValue] = Field(default_factory=dict)


class AirtableRecordListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[AirtableRecordData]
    total: int


class AirtableRecordListEntry(IntegrationFanOutEntry):
    data: AirtableRecordListData | None = None


class AirtableRecordEntry(IntegrationFanOutEntry):
    data: AirtableRecordData | None = None


class AirtableRecordMutationData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    reference: AirtableRecordReference


class AirtableRecordMutationEntry(IntegrationFanOutEntry):
    data: AirtableRecordMutationData | None = None


class AirtableListRecordsOutput(IntegrationFanOutOutput):
    results: list[AirtableRecordListEntry]


class AirtableGetRecordOutput(IntegrationFanOutOutput):
    results: list[AirtableRecordEntry]


class AirtableRecordMutationOutput(IntegrationFanOutOutput):
    results: list[AirtableRecordMutationEntry]
