# apps/api/integrations/notion/operations/query_data_source.py

"""Query bounded records from one Notion data source."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from services.integrations.http import IntegrationRequestPolicy

from ..client import NotionClient
from .utils import (
    compact_properties,
    normalized_search_result,
    pagination_envelope,
)


async def query_data_source(
    client: NotionClient,
    *,
    data_source_id: str,
    limit: int,
    start_cursor: str | None = None,
) -> dict[str, Any]:
    page_size = min(max(limit, 1), 50)
    body: dict[str, Any] = {"page_size": page_size, "result_type": "page"}
    if start_cursor:
        body["start_cursor"] = start_cursor
    payload = await client.post(
        f"data_sources/{quote(data_source_id, safe='')}/query",
        operation="query_data_source",
        policy=IntegrationRequestPolicy.READ,
        json=body,
    )
    envelope = pagination_envelope(payload, operation="query_data_source")
    records: list[dict[str, Any]] = []
    for item in envelope["results"][:page_size]:
        if not isinstance(item, Mapping):
            continue
        summary = normalized_search_result(item)
        if summary is None or summary["kind"] != "page":
            continue
        compacted = compact_properties(item.get("properties"), page_id=summary["id"])
        records.append(
            {
                **summary,
                "properties": compacted.values,
                "properties_truncated": compacted.truncated,
            }
        )
    request_status = envelope["request_status"]
    return {
        "records": records,
        "count": len(records),
        "has_more": envelope["has_more"],
        "next_cursor": envelope["next_cursor"],
        "incomplete": request_status is not None and request_status.get("type") == "incomplete",
    }
