# apps/api/services/kb/schemas.py

"""Knowledge-base search and document-read contracts."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from services.kb.domain import KB_DOCUMENT_TITLE_MAX_CHARS
from utils.pagination import OffsetPage

if TYPE_CHECKING:
    from models.kb import KBDocument


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
    processing_error: str | None
    summary: str | None
    external_url: str | None
    is_private: bool
    chunk_count: int
    content_md: str | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_document(cls, document: "KBDocument") -> "KBDocumentRead":
        """Serialize one canonical document model."""
        return cls(
            id=document.id,
            title=document.title,
            concept_id=document.concept_id,
            source_type=document.source_type,
            source_updated_at=document.source_updated_at,
            status=document.status,
            processing_error=document.processing_error,
            summary=document.summary,
            external_url=document.external_url,
            is_private=document.is_private,
            chunk_count=document.chunk_count,
            content_md=document.content_md,
            meta=document.meta,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class KBDocumentListItem(BaseModel):
    """Document metadata for the management list."""

    id: UUID
    title: str
    source_type: str
    status: str
    processing_error: str | None
    is_private: bool
    chunk_count: int
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_document(cls, document: "KBDocument") -> "KBDocumentListItem":
        return cls(
            id=document.id,
            title=document.title,
            source_type=document.source_type,
            status=document.status,
            processing_error=document.processing_error,
            is_private=document.is_private,
            chunk_count=document.chunk_count,
            created_by_user_id=document.created_by_user_id,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class KBDocumentsListResponse(OffsetPage):
    """Paginated workspace knowledge-document list."""

    documents: list[KBDocumentListItem]


class KBManualDocumentCreateRequest(BaseModel):
    """Create one member-authored markdown document."""

    title: str = Field(min_length=1, max_length=KB_DOCUMENT_TITLE_MAX_CHARS)
    content_md: str = Field(min_length=1)
    is_private: bool = False


class KBUrlDocumentCreateRequest(BaseModel):
    """Create one externally fetched document source."""

    url: str = Field(min_length=1, max_length=2_048)
    title: str = Field(min_length=1, max_length=KB_DOCUMENT_TITLE_MAX_CHARS)
    is_private: bool = False


class KBFileDocumentCreateRequest(BaseModel):
    """Create one document pinned to a workspace file revision."""

    file_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=KB_DOCUMENT_TITLE_MAX_CHARS)
    is_private: bool = False


class KBDocumentUpdateRequest(BaseModel):
    """Editable fields for one knowledge document."""

    title: str | None = Field(default=None, min_length=1, max_length=KB_DOCUMENT_TITLE_MAX_CHARS)
    content_md: str | None = Field(default=None, min_length=1)
    is_private: bool | None = None

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("title", "content_md", "is_private")
        ):
            raise ValueError("Knowledge document update fields cannot be null")
        return self
