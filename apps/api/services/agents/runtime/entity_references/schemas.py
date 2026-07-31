# apps/api/services/agents/runtime/entity_references/schemas.py

"""HTTP contracts for entity-reference search and hydration."""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from services.agents.runtime.entity_references.domain import EntityChoice


class EntityReferenceLookupRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    field_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    dependent_args: dict[str, Any] = Field(default_factory=dict)
    search: str | None = Field(default=None, max_length=500)
    exact_values: list[Any] | None = Field(default=None, max_length=50)
    cursor: str | None = Field(default=None, max_length=128)
    page_size: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_lookup_mode(self) -> "EntityReferenceLookupRequest":
        if self.exact_values is not None and self.search is not None:
            raise ValueError("Provide search or exact_values, not both")
        if self.exact_values is not None and (self.cursor is not None or not self.exact_values):
            raise ValueError("Exact hydration requires values and does not accept a cursor")
        return self


class EntityReferenceLookupResponse(BaseModel):
    entity_kind: str
    choices: list[EntityChoice]
    next_cursor: str | None = None
