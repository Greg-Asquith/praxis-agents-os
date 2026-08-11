# apps/api/services/integrations/context/results.py

"""Published result envelope for integration context execution."""

from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class IntegrationFanOutEntry(BaseModel):
    integration_resource_id: UUID
    connection_id: UUID
    provider_key: str
    external_id: str
    display_name: str
    status: Literal["success", "error"]
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None


class IntegrationFanOutOutput(BaseModel):
    results: list[IntegrationFanOutEntry]


def serialize_fan_out_results(
    items: Sequence[IntegrationFanOutEntry],
) -> list[dict[str, Any]]:
    """Serialize the stable nine-field outer envelope."""
    return [
        {
            "integration_resource_id": item.integration_resource_id,
            "connection_id": item.connection_id,
            "provider_key": item.provider_key,
            "external_id": item.external_id,
            "display_name": item.display_name,
            "status": item.status,
            "data": item.data,
            "error_code": item.error_code,
            "error_message": item.error_message,
        }
        for item in items
    ]
