# apps/api/services/artifacts/platform/schemas.py

"""Explicit review and concurrency contracts for platform Artifacts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from services.artifacts.schemas import ArtifactRead, ArtifactSummaryRead


class PlatformArtifactRead(ArtifactRead):
    published_version_id: UUID | None


class PlatformArtifactSummaryRead(ArtifactSummaryRead):
    published_version_id: UUID | None


class PlatformArtifactVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: UUID


class PlatformArtifactCreateRequest(PlatformArtifactVersionRequest):
    version_id: UUID
    request_id: UUID


class PlatformArtifactUpdateRequest(PlatformArtifactVersionRequest):
    content: str
    title: str | None = None


class PlatformArtifactRestoreRequest(PlatformArtifactVersionRequest):
    version_id: UUID
