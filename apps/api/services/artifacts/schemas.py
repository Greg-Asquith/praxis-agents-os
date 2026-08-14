# apps/api/services/artifacts/schemas.py

"""Artifact API and tool schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from services.agents.runtime.entity_references.domain import ArtifactReference


class ArtifactToolResult(BaseModel):
    artifact_id: str
    version_id: str
    title: str
    artifact_type: str
    reference: ArtifactReference


class ArtifactToolSummary(BaseModel):
    id: str
    reference: ArtifactReference
    title: str
    artifact_type: str
    version_count: int
    updated_at: datetime
    conversation_id: UUID | None


class ArtifactListToolResult(BaseModel):
    items: list[ArtifactToolSummary]
    total: int
    returned: int


class ArtifactReadToolResult(BaseModel):
    id: str
    reference: ArtifactReference
    title: str
    artifact_type: str
    revision_number: int
    updated_at: datetime
    content: str | None
    truncated: bool
    size_bytes: int
    content_type: str
    note: str | None = None


class ArtifactVersionRead(BaseModel):
    id: UUID
    created_at: datetime
    created_by_user_id: UUID | None
    created_by_agent_id: UUID | None
    created_by_system: bool
    size_bytes: int
    revision_number: int
    revision_kind: str
    restored_from_revision_id: UUID | None


class ArtifactBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    agent_id: UUID | None
    conversation_id: UUID | None
    run_id: UUID | None
    current_version_id: UUID
    artifact_type: str
    title: str
    created_at: datetime
    updated_at: datetime


class ArtifactSummaryRead(ArtifactBaseRead):
    version_count: int


class ArtifactRead(ArtifactBaseRead):
    versions: list[ArtifactVersionRead] = Field(default_factory=list)


class ArtifactListResponse(BaseModel):
    items: list[ArtifactSummaryRead]
    total: int
    limit: int
    offset: int


class ArtifactVersionContentRead(BaseModel):
    content: str | None = None
    content_type: str
    size_bytes: int
    download_url: str | None = None


class ArtifactViewUrl(BaseModel):
    url: str
    expires_at: datetime


class ArtifactUpdateRequest(BaseModel):
    content: str
    title: str | None = None


class ArtifactShareCreateRequest(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1)


class ArtifactShareCreated(BaseModel):
    id: UUID
    share_url: str
    token_prefix: str
    expires_at: datetime
    version_id: UUID


class ArtifactShareRead(BaseModel):
    id: UUID
    token_prefix: str
    expires_at: datetime
    version_id: UUID
    created_at: datetime
    created_by_user_id: UUID | None
    creator_display: str | None
    revoked_at: datetime | None
    revoked_by_user_id: UUID | None
    last_accessed_at: datetime | None
    access_count: int


class ArtifactShareListResponse(BaseModel):
    items: list[ArtifactShareRead]
