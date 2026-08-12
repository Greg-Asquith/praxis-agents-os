# apps/api/integrations/airtable/operations/create_record.py

"""Create one Airtable record."""

from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import AirtableClient


async def create_record(
    client: AirtableClient,
    *,
    base_id: str,
    table: str,
    fields: dict[str, Any],
) -> dict[str, str]:
    payload = await client.post(
        f"{quote(base_id, safe='')}/{quote(table, safe='')}",
        operation="create_record",
        policy=IntegrationRequestPolicy.MUTATION,
        json={"fields": fields},
    )
    record_id = str(payload.get("id", "")).strip() if isinstance(payload, dict) else ""
    if not record_id:
        raise IntegrationValidationError(
            "Airtable create response did not include a record id",
            provider_key="airtable",
            operation="create_record",
        )
    return {"record_id": record_id}
