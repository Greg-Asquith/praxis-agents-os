# apps/api/services/skills/documents/domain.py

"""Contracts for skill document upload and markdown access."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SKILL_DOC_NAME_PATTERN = r"^[a-z0-9]+(_[a-z0-9]+)*$"
_SKILL_DOC_NAME_RE = re.compile(SKILL_DOC_NAME_PATTERN)

SkillDocumentStatus = Literal["ready", "failed"]


class SkillDocumentConversionError(Exception):
    """Raised when a skill document cannot be converted to markdown."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SkillDocumentEntry(BaseModel):
    """Manifest entry stored in Skill.documentation_refs."""

    original: str = Field(min_length=1, max_length=1024)
    markdown: str | None = Field(default=None, max_length=1024)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=1)
    markdown_size_bytes: int | None = Field(default=None, ge=0)
    status: SkillDocumentStatus
    error: str | None = None
    updated_at: datetime


class SkillDocumentUploadRequest(BaseModel):
    """Client-declared document metadata used to create a direct-upload grant."""

    document_name: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=1)

    @field_validator("document_name")
    @classmethod
    def normalize_document_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Document name cannot be blank")
        if not _SKILL_DOC_NAME_RE.fullmatch(normalized):
            raise ValueError(
                f"document_name must match snake_case pattern {SKILL_DOC_NAME_PATTERN}"
            )
        return normalized

    @field_validator("filename", "content_type")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class SkillDocumentConfirmRequest(BaseModel):
    """Request body for confirming a direct-uploaded skill document."""

    upload_token: str = Field(min_length=1, max_length=4096)

    @field_validator("upload_token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Upload token cannot be blank")
        return normalized


class SkillDocumentRead(SkillDocumentEntry):
    """API representation of one skill document manifest entry."""

    name: str


class SkillDocumentsListResponse(BaseModel):
    """List response for a skill's uploaded documents."""

    documents: list[SkillDocumentRead]
    total: int


class SkillDocumentMarkdownResponse(BaseModel):
    """Markdown content for one ready skill document."""

    name: str
    content: str
    truncated: bool = False

