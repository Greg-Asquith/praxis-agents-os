# apps/api/services/integrations/connections/schemas.py

"""Typed request and response contracts for integration connections."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from utils.pagination import OffsetPage


class SecretReferenceInput(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)


class OAuthConnectRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=64)
    owner_scope: Literal["user", "workspace"]
    label: str = Field(min_length=1, max_length=120)
    next_path: str | None = Field(default=None, max_length=2048)
    connection_id: UUID | None = None


class OAuthConnectResponse(BaseModel):
    authorization_url: str
    state: str
    connection_id: UUID


class OAuthCallbackRequest(BaseModel):
    state: str = Field(min_length=1, max_length=4096)
    code: str | None = Field(default=None, max_length=4096)
    error: str | None = Field(default=None, max_length=255)


class ApiKeyConnectRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    api_key: SecretStr | None = None
    secret_reference: SecretReferenceInput | None = None

    @model_validator(mode="after")
    def exactly_one_secret_source(self) -> Self:
        if (self.api_key is None) == (self.secret_reference is None):
            raise ValueError("Exactly one of api_key or secret_reference is required")
        if self.api_key is not None and not self.api_key.get_secret_value().strip():
            raise ValueError("api_key cannot be blank")
        return self


class RenameConnectionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class ProviderRead(BaseModel):
    provider_key: str
    display_name: str
    auth_modes: tuple[str, ...]
    owner_scope: Literal["user", "workspace"]
    oauth_scopes: tuple[str, ...]
    resource_types: tuple[str, ...]
    required_form_fields: tuple[str, ...]
    capability_flags: frozenset[str]
    requires_discovery: bool
    configured: bool


class CredentialMetadataRead(BaseModel):
    auth_mode: str
    secret_reference: str | None
    token_expires_at: datetime | None
    granted_scopes: list[str] | None
    principal_fingerprint: str
    external_principal_label: str | None
    last_refreshed_at: datetime | None
    last_refresh_error_code: str | None


class ConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_key: str
    label: str
    owner_scope: Literal["user", "workspace"]
    owner_user_id: UUID | None
    owner_workspace_id: UUID | None
    status: str
    status_reason: str | None
    connected_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    duplicate_of_connection_ids: list[UUID] = Field(default_factory=list)
    credential: CredentialMetadataRead | None = None


class OAuthCallbackResponse(BaseModel):
    connection: ConnectionRead
    next_path: str | None = None


class ConnectionListResponse(OffsetPage):
    items: list[ConnectionRead]


class ConnectionTestResponse(BaseModel):
    connection_id: UUID
    status: str
    external_principal_label: str | None = None


class ConnectionRefreshResponse(BaseModel):
    connection_id: UUID
    status: str
    token_expires_at: datetime | None
