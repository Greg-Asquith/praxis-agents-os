# apps/api/services/integrations/file_sources/schemas.py

"""Request and response contracts for viewing or saving a provider file."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IntegrationFileSourceCreate(BaseModel):
    provider_key: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=100)
    # A scoped entity reference from a tool result; the provider's reference model validates it.
    reference: dict[str, Any]


class IntegrationFileSaveRead(BaseModel):
    file_id: UUID
    name: str
    content_type: str
    size_bytes: int
