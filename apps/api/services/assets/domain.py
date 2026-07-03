# apps/api/services/assets/domain.py

"""Pydantic contracts for user and workspace asset uploads."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.storage.domain import SignedUpload, StorageBucket


class AssetKind(StrEnum):
    """Application-managed public asset categories."""

    USER_AVATAR = "user_avatar"
    WORKSPACE_ICON = "workspace_icon"
    SKILL_DOCUMENT = "skill_document"


class AssetUploadRequest(BaseModel):
    """Client-declared file metadata used to create a direct-upload grant."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=1)

    @field_validator("filename", "content_type")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class AssetUploadGrant(BaseModel):
    """API-granted upload capability plus the API confirmation token."""

    upload: SignedUpload
    upload_token: str
    max_size_bytes: int
    expires_at: datetime


class AssetConfirmRequest(BaseModel):
    """Request body for confirming a direct-uploaded asset."""

    upload_token: str = Field(min_length=1, max_length=4096)

    @field_validator("upload_token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Upload token cannot be blank")
        return normalized


class AssetUploadTokenPayload(BaseModel):
    """Validated JWT payload for an asset upload grant."""

    model_config = ConfigDict(populate_by_name=True)

    token_type: Literal["asset_upload"] = Field(alias="type")
    kind: AssetKind
    actor_user_id: UUID
    target_user_id: UUID | None = None
    workspace_id: UUID | None = None
    bucket: StorageBucket
    object_key: str = Field(min_length=1, max_length=1024)
    content_type: str = Field(min_length=1, max_length=128)
    max_size_bytes: int = Field(ge=1)
    jti: str = Field(min_length=1, max_length=128)
    iat: int = Field(ge=0)
    exp: int = Field(ge=0)
