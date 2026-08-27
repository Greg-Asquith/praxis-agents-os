# apps/api/integrations/notion/operations/search.py

"""Search bounded Notion page and data-source title matches."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from .utils import NotionObjectKind, normalized_search_result, pagination_envelope


async def search(
    client: NotionClient,
    *,
    query: str | None,
    kind: NotionObjectKind,
    limit: int,
    start_cursor: str | None = None,
) -> dict[str, Any]:
    page_size = min(max(limit, 1), 100)
    body: dict[str, Any] = {
        "sort": {"timestamp": "last_edited_time", "direction": "descending"},
        "page_size": page_size,
    }
    if query:
        body["query"] = query
    if kind != "all":
        body["filter"] = {"property": "object", "value": kind}
    if start_cursor:
        body["start_cursor"] = start_cursor
    payload = await client.post(
        "search",
        operation="search",
        policy=IntegrationRequestPolicy.READ,
        json=body,
    )
    envelope = pagination_envelope(payload, operation="search")
    items = [
        result
        for item in envelope["results"][:page_size]
        if (result := normalized_search_result(item)) is not None
        and (kind == "all" or result["kind"] == kind)
    ]
    return {
        "items": items,
        "count": len(items),
        "has_more": envelope["has_more"],
        "next_cursor": envelope["next_cursor"],
    }
