# apps/api/integrations/airtable/operations/update_record.py

"""Update one Airtable record with PATCH semantics."""

from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import AirtableClient


async def update_record(
    client: AirtableClient,
    *,
    base_id: str,
    table: str,
    record_id: str,
    fields: dict[str, Any],
) -> dict[str, str]:
    payload = await client.patch(
        f"{quote(base_id, safe='')}/{quote(table, safe='')}/{quote(record_id, safe='')}",
        operation="update_record",
        policy=IntegrationRequestPolicy.MUTATION,
        json={"fields": fields},
    )
    updated_id = str(payload.get("id", "")).strip() if isinstance(payload, dict) else ""
    if not updated_id:
        raise IntegrationValidationError(
            "Airtable update response did not include a record id",
            provider_key="airtable",
            operation="update_record",
        )
    return {"record_id": updated_id}
