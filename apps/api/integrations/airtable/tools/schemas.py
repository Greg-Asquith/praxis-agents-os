# apps/api/integrations/airtable/tools/schemas.py

"""Typed Airtable tool-result contracts."""

from uuid import UUID

from pydantic import BaseModel

from services.agents.runtime.untrusted import UntrustedJsonValue


class AirtableFanOutEntry(BaseModel):
    integration_resource_id: UUID
    connection_id: UUID
    provider_key: str
    external_id: str
    display_name: str
    status: str
    data: dict[str, UntrustedJsonValue] | None = None
    error_code: str | None = None
    error_message: str | None = None


class AirtableOutput(BaseModel):
    results: list[AirtableFanOutEntry]
