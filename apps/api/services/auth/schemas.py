# apps/api/services/auth/schemas.py

"""Pydantic contracts for authentication routes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.user import User
from utils.validation import normalize_email


class AuthUser(BaseModel):
    """Public authenticated-user projection."""

    id: UUID
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    default_workspace_id: UUID | None = None
    totp_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_user(cls, user: User) -> "AuthUser":
        return cls.model_validate(user)


class AuthProvider(BaseModel):
    name: str
    display_name: str
    icon: str


class AuthProvidersResponse(BaseModel):
    providers: list[AuthProvider]


class ConnectedIdentity(BaseModel):
    """A single linked sign-in method (OAuth provider) for a user."""

    provider: str
    email: str | None = None
    email_verified: bool
    created_at: datetime


class IdentitiesResponse(BaseModel):
    """The current user's connected sign-in methods."""

    has_password: bool
    identities: list[ConnectedIdentity]


class AuthSession(BaseModel):
    expires_at: datetime
    twofa_verified: bool


class AuthResponse(BaseModel):
    user: AuthUser | None = None
    session: AuthSession
    requires_twofa: bool = False


class MessageResponse(BaseModel):
    message: str


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=1024)
    display_name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class OAuthAuthorizationUrlRequest(BaseModel):
    redirect_uri: str | None = Field(default=None, max_length=2048)
    next_path: str | None = Field(default=None, max_length=1024)


class OAuthAuthorizationUrlResponse(BaseModel):
    provider: str
    authorization_url: str
    state: str
    expires_at: datetime


class OAuthCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=4096)
    redirect_uri: str | None = Field(default=None, max_length=2048)


class CurrentUserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)

    @field_validator("display_name", "avatar_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class TotpSetupResponse(BaseModel):
    provisioning_uri: str
    secret: str


class TotpEnableRequest(BaseModel):
    token: str = Field(min_length=6, max_length=16)


class TotpVerifyRequest(BaseModel):
    token: str | None = Field(default=None, min_length=6, max_length=16)
    backup_code: str | None = Field(default=None, min_length=6, max_length=32)


class TotpDisableRequest(BaseModel):
    token: str | None = Field(default=None, min_length=6, max_length=16)
    backup_code: str | None = Field(default=None, min_length=6, max_length=32)


class TotpEnableResponse(BaseModel):
    message: str
    backup_codes: list[str]


class SessionDevice(BaseModel):
    id: UUID
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    last_accessed: datetime
    expires_at: datetime
    current: bool = False


class SessionsResponse(BaseModel):
    sessions: list[SessionDevice]
