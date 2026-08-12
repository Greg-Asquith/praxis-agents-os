# apps/api/integrations/airtable/tools/schemas.py

"""Typed Airtable tool-result contracts."""

from services.agents.runtime.untrusted import UntrustedJsonValue
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)


class AirtableFanOutEntry(IntegrationFanOutEntry):
    data: dict[str, UntrustedJsonValue] | None = None


class AirtableOutput(IntegrationFanOutOutput):
    results: list[AirtableFanOutEntry]
