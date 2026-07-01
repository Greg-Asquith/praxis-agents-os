# apps/api/services/users/schemas.py

"""Pydantic contracts for user-management routes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.user import User
from utils.validation import normalize_email


class UserRead(BaseModel):
    id: UUID
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    default_workspace_id: UUID | None = None
    totp_enabled: bool
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_user(cls, user: User) -> "UserRead":
        return cls.model_validate(user)


class UsersListResponse(BaseModel):
    users: list[UserRead]
    total: int
    limit: int
    offset: int


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=1024)
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UserPasswordSetRequest(BaseModel):
    password: str = Field(min_length=8, max_length=1024)
