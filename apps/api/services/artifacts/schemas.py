# apps/api/services/artifacts/schemas.py

"""Artifact API and tool schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArtifactToolResult(BaseModel):
    artifact_id: str
    version_id: str
    title: str
    artifact_type: str


class ArtifactVersionRead(BaseModel):
    id: UUID
    created_at: datetime
    created_by_user_id: UUID | None
    created_by_agent_id: UUID | None
    created_by_system: bool
    size_bytes: int


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
