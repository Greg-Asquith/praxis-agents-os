# apps/api/integrations/outlook_mail/tools/schemas.py

"""Typed Outlook read result contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ..references import OutlookAttachmentReference, OutlookMessageReference

type UntrustedText = str | UntrustedNode


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Address(_StrictModel):
    name: UntrustedText
    address: UntrustedText


class Message(_StrictModel):
    reference: OutlookMessageReference
    subject: UntrustedText
    sender: Address = Field(alias="from")
    to_count: int = Field(ge=0)
    received_at: str | None
    is_read: bool
    has_attachments: bool
    preview: UntrustedText
    importance: Literal["low", "normal", "high"]
    focused: bool


class Attachment(_StrictModel):
    reference: OutlookAttachmentReference
    name: UntrustedText
    content_type: UntrustedText
    size_bytes: int = Field(ge=0)
    is_inline: bool


class SearchData(_StrictModel):
    messages: list[Message] = Field(max_length=25)
    count: int = Field(ge=0, le=25)
    mailbox_time_zone: str | None


class MessageData(Message):
    to: list[Address] = Field(max_length=50)
    cc: list[Address] = Field(max_length=50)
    body: UntrustedText
    truncated: bool
    attachments: list[Attachment] = Field(max_length=50)
    conversation_id: UntrustedText
    internet_message_id: UntrustedText
    web_link: UntrustedText
    mailbox_time_zone: str | None


class Folder(_StrictModel):
    name: UntrustedText
    well_known_name: str | None
    unread_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    child_folder_count: int = Field(ge=0)


class FoldersData(_StrictModel):
    folders: list[Folder] = Field(max_length=200)
    mailbox_time_zone: str | None


class AttachmentData(_StrictModel):
    name: UntrustedText
    content_type: UntrustedText
    size_bytes: int = Field(ge=0)
    markdown: UntrustedText
    truncated: bool
    source: Literal["converted", "text"]
    mailbox_time_zone: str | None


class Person(_StrictModel):
    name: UntrustedText
    address: UntrustedText
    job_title: UntrustedText
    department: UntrustedText


class PeopleData(_StrictModel):
    people: list[Person] = Field(max_length=25)
    count: int = Field(ge=0, le=25)
    mailbox_time_zone: str | None


class SearchEntry(IntegrationFanOutEntry):
    data: SearchData | None = None


class MessageEntry(IntegrationFanOutEntry):
    data: MessageData | None = None


class FoldersEntry(IntegrationFanOutEntry):
    data: FoldersData | None = None


class AttachmentEntry(IntegrationFanOutEntry):
    data: AttachmentData | None = None


class PeopleEntry(IntegrationFanOutEntry):
    data: PeopleData | None = None


class SearchOutput(IntegrationFanOutOutput):
    results: list[SearchEntry]


class MessageOutput(IntegrationFanOutOutput):
    results: list[MessageEntry]


class FoldersOutput(IntegrationFanOutOutput):
    results: list[FoldersEntry]


class AttachmentOutput(IntegrationFanOutOutput):
    results: list[AttachmentEntry]


class PeopleOutput(IntegrationFanOutOutput):
    results: list[PeopleEntry]
