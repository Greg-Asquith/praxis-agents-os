# apps/api/integrations/google_ads/tools/schemas.py

"""Typed Google Ads tool-result contracts."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class GoogleAdsFanOutEntry(BaseModel):
    integration_resource_id: UUID
    connection_id: UUID
    provider_key: str
    external_id: str
    display_name: str
    status: str
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None


class GoogleAdsOutput(BaseModel):
    results: list[GoogleAdsFanOutEntry]
