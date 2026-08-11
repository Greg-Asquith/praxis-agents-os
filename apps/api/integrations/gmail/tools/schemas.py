# apps/api/integrations/gmail/tools/schemas.py

"""Typed Gmail tool-result contracts."""

from pydantic import BaseModel

from integrations.gmail.references import GmailMessageReference
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

type UntrustedText = str | UntrustedNode


class GmailMessageSummary(BaseModel):
    message_id: str
    reference: GmailMessageReference
    sender: UntrustedText
    to: UntrustedText
    subject: UntrustedText
    date: UntrustedText
    snippet: UntrustedText


class GmailSearchData(BaseModel):
    messages: list[GmailMessageSummary]
    total: int


class GmailMessageData(BaseModel):
    message_id: str
    sender: UntrustedText
    to: UntrustedText
    subject: UntrustedText
    date: UntrustedText
    body: UntrustedText
    truncated: bool


class GmailSendData(BaseModel):
    message_id: str


class GmailSearchEntry(IntegrationFanOutEntry):
    data: GmailSearchData | None = None


class GmailReadEntry(IntegrationFanOutEntry):
    data: GmailMessageData | None = None


class GmailSendEntry(IntegrationFanOutEntry):
    data: GmailSendData | None = None


class GmailSearchOutput(IntegrationFanOutOutput):
    results: list[GmailSearchEntry]


class GmailReadOutput(IntegrationFanOutOutput):
    results: list[GmailReadEntry]


class GmailSendOutput(IntegrationFanOutOutput):
    results: list[GmailSendEntry]
