# apps/api/integrations/airtable/operations/get_record.py

"""Get one Airtable record."""

from typing import Any
from urllib.parse import quote

from services.integrations.http import IntegrationRequestPolicy

from ..client import AirtableClient
from .utils import record_payload


async def get_record(
    client: AirtableClient,
    *,
    base_id: str,
    table: str,
    record_id: str,
) -> dict[str, Any]:
    payload: Any = await client.get(
        f"{quote(base_id, safe='')}/{quote(table, safe='')}/{quote(record_id, safe='')}",
        operation="get_record",
        policy=IntegrationRequestPolicy.READ,
    )
    return record_payload(payload)
