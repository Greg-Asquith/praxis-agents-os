# apps/api/integrations/notion/operations/get_data_source.py

"""Retrieve and normalize one Notion data source."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from .utils import data_source_title, notion_id, untrusted_text


async def get_data_source(client: NotionClient, *, data_source_id: str) -> dict[str, Any]:
    payload = await client.get(
        f"data_sources/{quote(data_source_id, safe='')}",
        operation="get_data_source",
        policy=IntegrationRequestPolicy.READ,
    )
    if not isinstance(payload, Mapping) or not notion_id(payload):
        raise IntegrationValidationError(
            "Notion returned an invalid data source response",
            provider_key="notion",
            operation="get_data_source",
        )
    normalized_id = notion_id(payload)
    title = data_source_title(payload) or "(untitled)"
    return {
        "id": normalized_id,
        "title": untrusted_text(
            title,
            source_kind="notion_data_source",
            source_ref=normalized_id,
        ),
        "url": str(payload.get("url", ""))[:2_000],
        "last_edited_time": str(payload.get("last_edited_time", ""))[:100],
    }
