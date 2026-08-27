# apps/api/integrations/notion/operations/get_page_markdown.py

"""Retrieve one bounded Notion page as enhanced Markdown."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from .utils import bounded_utf8, untrusted_text

MAX_MARKDOWN_BYTES = 64 * 1024


async def get_page_markdown(client: NotionClient, *, page_id: str) -> dict[str, Any]:
    payload = await client.get(
        f"pages/{quote(page_id, safe='')}/markdown",
        operation="get_page_markdown",
        policy=IntegrationRequestPolicy.READ,
    )
    if not isinstance(payload, Mapping) or not isinstance(payload.get("markdown"), str):
        raise IntegrationValidationError(
            "Notion returned an invalid page Markdown response",
            provider_key="notion",
            operation="get_page_markdown",
        )
    markdown, bytes_returned, truncated = bounded_utf8(
        payload["markdown"], max_bytes=MAX_MARKDOWN_BYTES
    )
    unknown = payload.get("unknown_block_ids")
    return {
        "markdown": untrusted_text(
            markdown,
            source_kind="notion_page",
            source_ref=page_id,
        ),
        "bytes_returned": bytes_returned,
        "truncated": truncated,
        "provider_truncated": bool(payload.get("truncated")),
        "unknown_block_count": min(len(unknown), 100) if isinstance(unknown, list) else 0,
    }
