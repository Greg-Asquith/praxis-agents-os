# apps/api/integrations/sharepoint/operations/search_items.py

"""Searches a bounded set of items within one selected drive."""

from urllib.parse import quote

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import (
    ITEM_SELECT,
    invalid_response,
    is_local_item,
    item_kind,
    item_path,
    item_result,
    object_payload,
    search_next_link,
)


async def search_items(
    client: MicrosoftGraphClient, *, drive_id: str, query: str, limit: int = 10
) -> dict:
    if not 1 <= limit <= 25 or not 1 <= len(query) <= 200 or not query.strip():
        raise ValueError(
            "SharePoint search requires a query of 1-200 characters and a limit of 1-25."
        )
    escaped = quote(query.replace("'", "''"), safe="")
    path = f"{item_path(drive_id)}/search(q='{escaped}')"
    next_path = path
    params = {"$select": ITEM_SELECT, "$top": limit}
    items = []
    scanned = 0
    for _ in range(5):
        payload = object_payload(
            await client.get(
                next_path,
                operation="search_files",
                policy=IntegrationRequestPolicy.READ,
                params=params,
            ),
            operation="search_files",
        )
        values = payload.get("value")
        if not isinstance(values, list):
            raise invalid_response("search_files")
        page = values[: limit - scanned]
        scanned += len(page)
        items.extend(
            item_result(item, drive_id=drive_id, operation="search_files")
            for item in page
            if isinstance(item, dict)
            and is_local_item(item, drive_id)
            and item_kind(item, operation="search_files") is not None
        )
        if scanned >= limit or not payload.get("@odata.nextLink"):
            break
        next_path = search_next_link(payload["@odata.nextLink"], path)
        params = None
    return {"items": items, "count": len(items)}
