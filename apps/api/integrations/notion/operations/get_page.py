# apps/api/integrations/notion/operations/get_page.py

"""Retrieve and normalize one Notion page."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from .utils import notion_id, page_title, untrusted_text


async def get_page(client: NotionClient, *, page_id: str) -> dict[str, Any]:
    payload = await client.get(
        f"pages/{quote(page_id, safe='')}",
        operation="get_page",
        policy=IntegrationRequestPolicy.READ,
    )
    if not isinstance(payload, Mapping) or not notion_id(payload):
        raise IntegrationValidationError(
            "Notion returned an invalid page response",
            provider_key="notion",
            operation="get_page",
        )
    normalized_id = notion_id(payload)
    title = page_title(payload) or "(untitled)"
    return {
        "id": normalized_id,
        "title": untrusted_text(title, source_kind="notion_page", source_ref=normalized_id),
        "url": str(payload.get("url", ""))[:2_000],
        "last_edited_time": str(payload.get("last_edited_time", ""))[:100],
    }
