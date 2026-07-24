# apps/api/services/kb/schemas.py

"""Knowledge-base search and document-read contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class KBSearchHit(BaseModel):
    """One cited knowledge-base chunk."""

    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    context_line: str | None
    char_start: int
    char_end: int
    meta: dict[str, Any]
    pending_embedding: bool
    title: str
    source_type: str
    external_url: str | None
    is_private: bool
    score: float
    sources: list[str]


class KBSearchResult(BaseModel):
    """Bounded search response with an explicit degradation mode."""

    results: list[KBSearchHit]
    mode: Literal["hybrid", "lexical_fallback"]
    query: str


class KBDocumentRead(BaseModel):
    """Workspace-visible canonical knowledge-base document."""

    id: UUID
    title: str
    concept_id: str | None
    source_type: str
    source_updated_at: datetime | None
    status: str
    summary: str | None
    external_url: str | None
    is_private: bool
    chunk_count: int
    content_md: str | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime
