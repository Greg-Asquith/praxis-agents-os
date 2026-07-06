# apps/api/services/files/domain.py

"""Pydantic contracts for workspace file services."""

import re
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from services.storage.domain import SignedDownload, SignedUpload
from utils.validation import normalize_optional_text

_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class FileUploadRequest(BaseModel):
    """Client-declared metadata used to request a signed file upload."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=1)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    file_id: UUID | None = None
    allow_duplicate_content: bool = False

    @field_validator("filename", "content_type")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @field_validator("content_hash")
    @classmethod
    def normalize_content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("content_hash must be a 64-character sha256 hex digest")
        return normalized


class FileUploadGrant(BaseModel):
    """Signed upload grant plus the API confirmation token."""

    upload: SignedUpload
    upload_token: str
    max_size_bytes: int
    expires_at: datetime
    over_soft_limit: bool = False
    file_id: UUID


class FileUploadResult(BaseModel):
    """Request-upload response: either a dedup hit or an upload grant."""

    deduplicated: bool = False
    file: "FileRead | None" = None
    grant: FileUploadGrant | None = None

    @model_validator(mode="after")
    def require_exactly_one_result(self) -> Self:
        has_file = self.file is not None
        has_grant = self.grant is not None
        if has_file == has_grant:
            raise ValueError("Exactly one of file or grant must be populated")
        if self.deduplicated != has_file:
            raise ValueError("deduplicated must match the file result")
        return self


class FileConfirmRequest(BaseModel):
    """Request body for confirming a direct-uploaded workspace file."""

    upload_token: str = Field(min_length=1, max_length=4096)

    @field_validator("upload_token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Upload token cannot be blank")
        return normalized


class FileEditRequest(BaseModel):
    """Text edit request for an editable file."""

    content: str
    expected_current_revision_id: UUID


class FileUpdateRequest(BaseModel):
    """Metadata update request for a workspace file."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)

    @field_validator("name", "description")
    @classmethod
    def normalize_optional_text_fields(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class FileRestoreRequest(BaseModel):
    """Roll-forward restore request for a prior file revision."""

    revision_id: UUID
    expected_current_revision_id: UUID


class FileDownloadRequest(BaseModel):
    """Signed download request for a file revision."""

    revision_id: UUID | None = None
    force_download: bool = True


class FileRead(BaseModel):
    """API representation of a workspace file."""

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None = None
    category: str
    content_type: str
    extension: str
    size_bytes: int
    content_hash: str
    current_revision_id: UUID
    revision_count: int
    processing_status: str
    processing_error: str | None = None
    created_at: datetime
    updated_at: datetime


class FileRevisionRead(BaseModel):
    """API representation of an immutable file revision."""

    id: UUID
    revision_number: int
    revision_kind: str
    content_type: str
    size_bytes: int
    content_hash: str
    created_by_user_id: UUID | None = None
    created_by_agent_id: UUID | None = None
    created_by_system: bool
    restored_from_revision_id: UUID | None = None
    created_at: datetime


class FileListResponse(BaseModel):
    """List response for workspace files."""

    files: list[FileRead]
    total: int


class FileRevisionsListResponse(BaseModel):
    """List response for one file's revisions."""

    revisions: list[FileRevisionRead]
    total: int


class FileDownloadGrant(BaseModel):
    """Signed download grant for a workspace file object."""

    download: SignedDownload
    expires_at: datetime


class FilesUsageResponse(BaseModel):
    """Workspace file storage usage counter."""

    used_bytes: int
    soft_limit_bytes: int
    over_soft_limit: bool


class FilesProcessingSummary(BaseModel):
    """Workspace file processing status counts."""

    pending: int
    processing: int
    ready: int
    error: int
    in_flight_jobs: int
