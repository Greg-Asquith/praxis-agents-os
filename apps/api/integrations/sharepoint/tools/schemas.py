# apps/api/integrations/sharepoint/tools/schemas.py

"""Typed SharePoint listing, search, file content, and link results."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ..references import SharePointDriveItemReference

type UntrustedText = str | UntrustedNode


class DriveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: SharePointDriveItemReference
    name: UntrustedText
    kind: Literal["file", "folder"]
    path: UntrustedText
    size_bytes: int = Field(ge=0)
    content_type: UntrustedText
    modified_at: UntrustedText
    web_url: UntrustedText


class FolderData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DriveItem] = Field(max_length=200)
    count: int = Field(ge=0, le=200)
    has_more: bool


class FolderEntry(IntegrationFanOutEntry):
    data: FolderData | None = None


class FolderOutput(IntegrationFanOutOutput):
    results: list[FolderEntry]


class SearchData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DriveItem] = Field(max_length=25)
    count: int = Field(ge=0, le=25)


class SearchEntry(IntegrationFanOutEntry):
    data: SearchData | None = None


class SharePointSearchOutput(IntegrationFanOutOutput):
    results: list[SearchEntry]


class SharePointFileData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: UntrustedText
    content_type: UntrustedText
    size_bytes: int = Field(ge=0)
    modified_at: UntrustedText
    web_url: UntrustedText
    markdown: UntrustedText
    offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    limit_reached: bool
    hint: str | None = None
    truncated: bool
    source: Literal["converted", "text"]


class SharePointFileEntry(IntegrationFanOutEntry):
    data: SharePointFileData | None = None


class SharePointFileOutput(IntegrationFanOutOutput):
    results: list[SharePointFileEntry]


class SharePointLibraryHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library: UntrustedText


class SharePointLinkEntry(IntegrationFanOutEntry):
    data: DriveItem | SharePointLibraryHint | None = None


class SharePointLinkOutput(IntegrationFanOutOutput):
    results: list[SharePointLinkEntry]


class SharePointFileMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(ge=0)
    excerpt: UntrustedText


class SharePointFindData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: UntrustedText
    web_url: UntrustedText
    total_bytes: int = Field(ge=0)
    limit_reached: bool
    matches: list[SharePointFileMatch] = Field(max_length=25)
    count: int = Field(ge=0, le=25)
    has_more: bool


class SharePointFindEntry(IntegrationFanOutEntry):
    data: SharePointFindData | None = None


class SharePointFindOutput(IntegrationFanOutOutput):
    results: list[SharePointFindEntry]
