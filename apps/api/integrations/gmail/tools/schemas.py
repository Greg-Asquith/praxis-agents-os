# apps/api/integrations/gmail/tools/schemas.py

"""Typed Gmail tool-result contracts."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class GmailMessageSummary(BaseModel):
    message_id: str
    sender: str
    to: str
    subject: str
    date: str
    snippet: str


class GmailSearchData(BaseModel):
    messages: list[GmailMessageSummary]
    total: int


class GmailMessageData(BaseModel):
    message_id: str
    sender: str
    to: str
    subject: str
    date: str
    body: str
    truncated: bool


class GmailSendData(BaseModel):
    message_id: str


class GmailFanOutEntry(BaseModel):
    integration_resource_id: UUID
    connection_id: UUID
    provider_key: str
    external_id: str
    display_name: str
    status: str
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None


class GmailSearchEntry(GmailFanOutEntry):
    data: GmailSearchData | None = None


class GmailReadEntry(GmailFanOutEntry):
    data: GmailMessageData | None = None


class GmailSendEntry(GmailFanOutEntry):
    data: GmailSendData | None = None


class GmailSearchOutput(BaseModel):
    results: list[GmailSearchEntry]


class GmailReadOutput(BaseModel):
    results: list[GmailReadEntry]


class GmailSendOutput(BaseModel):
    results: list[GmailSendEntry]
