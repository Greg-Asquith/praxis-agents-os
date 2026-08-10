# apps/api/services/audit_events/integration_operation_detail.py

"""Bounded, provider-neutral detail for audited integration operations."""

import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type AuditDetailValue = (
    str | int | float | bool | list["AuditDetailValue"] | dict[str, "AuditDetailValue"] | None
)

MAX_INTEGRATION_OPERATION_DETAIL_BYTES = 1_000_000


class IntegrationOperationTarget(BaseModel):
    """The provider entity against which an operation was executed."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=1_000)
    display_name: str | None = Field(default=None, max_length=500)
    integration_resource_id: str | None = Field(default=None, max_length=100)
    attributes: dict[str, AuditDetailValue] = Field(default_factory=dict, max_length=32)


class IntegrationOperationChange(BaseModel):
    """One confirmed provider-side change and its operation-specific fields."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=64)
    entity_type: str = Field(min_length=1, max_length=100)
    external_ref: str | None = Field(default=None, max_length=1_000)
    fields: dict[str, AuditDetailValue] = Field(default_factory=dict, max_length=32)


class IntegrationOperationCounts(BaseModel):
    """Counts for outcomes that may intentionally omit item-level content."""

    model_config = ConfigDict(extra="forbid")

    applied: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0)


class IntegrationOperationDetail(BaseModel):
    """Versioned audit envelope reusable by provider integrations."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    target: IntegrationOperationTarget
    changes: list[IntegrationOperationChange] = Field(default_factory=list, max_length=500)
    counts: IntegrationOperationCounts

    @model_validator(mode="after")
    def enforce_serialized_size(self) -> Self:
        serialized = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if len(serialized) > MAX_INTEGRATION_OPERATION_DETAIL_BYTES:
            raise ValueError("Integration operation audit detail exceeds the 1,000,000-byte limit")
        return self
