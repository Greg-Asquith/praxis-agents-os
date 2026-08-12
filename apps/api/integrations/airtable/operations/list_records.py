# apps/api/integrations/airtable/operations/list_records.py

"""List bounded Airtable records from one base and table."""

from typing import Any
from urllib.parse import quote

from services.integrations.http import IntegrationRequestPolicy

from ..client import AirtableClient
from .utils import record_payload

MAX_RECORDS = 100


async def list_records(
    client: AirtableClient,
    *,
    base_id: str,
    table: str,
    view: str | None = None,
    filter_by_formula: str | None = None,
    max_records: int = MAX_RECORDS,
) -> dict[str, Any]:
    limit = min(max(max_records, 1), MAX_RECORDS)
    records: list[dict[str, Any]] = []
    offset: str | None = None
    seen_offsets: set[str] = set()
    while len(records) < limit:
        params: dict[str, Any] = {"maxRecords": limit - len(records)}
        if view:
            params["view"] = view
        if filter_by_formula:
            params["filterByFormula"] = filter_by_formula
        if offset:
            params["offset"] = offset
        payload = await client.get(
            f"{quote(base_id, safe='')}/{quote(table, safe='')}",
            operation="list_records",
            policy=IntegrationRequestPolicy.READ,
            params=params,
        )
        items = payload.get("records") if isinstance(payload, dict) else None
        if isinstance(items, list):
            records.extend(record_payload(item) for item in items[: limit - len(records)])
        next_offset = str(payload.get("offset", "")).strip() if isinstance(payload, dict) else ""
        if not next_offset or next_offset in seen_offsets:
            break
        seen_offsets.add(next_offset)
        offset = next_offset
    return {"records": records, "total": len(records)}
