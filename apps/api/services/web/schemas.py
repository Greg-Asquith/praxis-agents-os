# apps/api/services/web/schemas.py

"""Request and response contracts for saving a fetched page from a tool card."""

from uuid import UUID

from pydantic import BaseModel, Field


class FetchedPageSaveCreate(BaseModel):
    conversation_id: UUID
    url: str = Field(min_length=1, max_length=2_048)


class FetchedPageSaveRead(BaseModel):
    file_id: UUID
    name: str
    content_type: str
    size_bytes: int
