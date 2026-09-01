# apps/api/integrations/notion/tools/schemas.py

"""Typed Notion tool-result contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from integrations.notion.operations.utils import MAX_PROPERTIES
from integrations.notion.references import (
    NotionDataSourceReference,
    NotionPageReference,
)
from services.agents.runtime.untrusted import UntrustedJsonValue, UntrustedNode
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

type UntrustedText = str | UntrustedNode


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotionSearchItem(_StrictModel):
    kind: Literal["page", "data_source"]
    title: UntrustedText
    url: str
    last_edited_time: str
    reference: NotionPageReference | NotionDataSourceReference


class NotionSearchData(_StrictModel):
    items: Annotated[list[NotionSearchItem], Field(max_length=50)]
    count: int = Field(ge=0, le=50)
    has_more: bool
    next_cursor: str | None = None
    coverage_note: str


class NotionPageData(_StrictModel):
    reference: NotionPageReference
    title: UntrustedText
    markdown: UntrustedText
    url: str
    source_updated_at: str
    bytes_returned: int = Field(ge=0, le=65_536)
    truncated: bool
    provider_truncated: bool
    unknown_block_count: int = Field(ge=0, le=100)


class NotionRecordData(_StrictModel):
    reference: NotionPageReference
    title: UntrustedText
    url: str
    last_edited_time: str
    properties: Annotated[dict[str, UntrustedJsonValue], Field(max_length=MAX_PROPERTIES)]
    properties_truncated: bool


class NotionDataSourceQueryData(_StrictModel):
    records: Annotated[list[NotionRecordData], Field(max_length=50)]
    count: int = Field(ge=0, le=50)
    has_more: bool
    next_cursor: str | None = None
    incomplete: bool


class NotionMutationData(_StrictModel):
    outcome: Literal["applied", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=128)


class NotionCreatePageData(NotionMutationData):
    reference: NotionPageReference | None = None
    url: str | None = None
    title: str = Field(min_length=1, max_length=500)
    last_edited_time: str | None = Field(default=None, max_length=100)


class NotionUpdatePageContentData(NotionMutationData):
    reference: NotionPageReference
    applied_replacements: int = Field(ge=0, le=20)
    page_truncated: bool | None = None
    last_edited_time: str | None = Field(default=None, max_length=100)


class NotionUpdatePagePropertiesData(NotionMutationData):
    reference: NotionPageReference
    url: str | None = None
    last_edited_time: str | None = Field(default=None, max_length=100)


class NotionSearchEntry(IntegrationFanOutEntry):
    data: NotionSearchData | None = None


class NotionPageEntry(IntegrationFanOutEntry):
    data: NotionPageData | None = None


class NotionDataSourceQueryEntry(IntegrationFanOutEntry):
    data: NotionDataSourceQueryData | None = None


class NotionCreatePageEntry(IntegrationFanOutEntry):
    data: NotionCreatePageData | None = None


class NotionUpdatePageContentEntry(IntegrationFanOutEntry):
    data: NotionUpdatePageContentData | None = None


class NotionUpdatePagePropertiesEntry(IntegrationFanOutEntry):
    data: NotionUpdatePagePropertiesData | None = None


class NotionSearchOutput(IntegrationFanOutOutput):
    results: list[NotionSearchEntry]


class NotionPageOutput(IntegrationFanOutOutput):
    results: list[NotionPageEntry]


class NotionDataSourceQueryOutput(IntegrationFanOutOutput):
    results: list[NotionDataSourceQueryEntry]


class NotionCreatePageOutput(IntegrationFanOutOutput):
    results: list[NotionCreatePageEntry]


class NotionUpdatePageContentOutput(IntegrationFanOutOutput):
    results: list[NotionUpdatePageContentEntry]


class NotionUpdatePagePropertiesOutput(IntegrationFanOutOutput):
    results: list[NotionUpdatePagePropertiesEntry]
