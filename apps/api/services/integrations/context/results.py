# apps/api/services/integrations/context/results.py

"""Published result envelope for integration context execution."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from services.integrations.context.domain import ResolvedContextEntry


@dataclass(frozen=True)
class IntegrationContextResult:
    """Internal execution result retaining the authorized context entry."""

    entry: ResolvedContextEntry
    status: Literal["success", "error"]
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def integration_resource_id(self) -> UUID:
        return self.entry.integration_resource_id

    @property
    def connection_id(self) -> UUID:
        return self.entry.connection_id


class IntegrationFanOutEntry(BaseModel):
    """Safe model-facing result for one provider-owned resource scope."""

    model_config = ConfigDict(extra="forbid")

    provider_key: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)
    external_id: str = Field(
        min_length=1,
        max_length=512,
        description="Provider-owned resource scope identifier.",
    )
    display_name: str = Field(min_length=1, max_length=500)
    status: Literal["success", "error"]
    data: Any | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1000)


class IntegrationFanOutOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[IntegrationFanOutEntry]


def serialize_fan_out_results(
    items: Sequence[IntegrationContextResult],
) -> list[dict[str, Any]]:
    """Publish safe provider fields without internal authorization identifiers."""
    return [
        {
            "provider_key": item.entry.provider_key,
            "external_id": item.entry.external_id,
            "display_name": item.entry.display_name,
            "status": item.status,
            "data": item.data,
            "error_code": item.error_code,
            "error_message": item.error_message,
        }
        for item in items
    ]
