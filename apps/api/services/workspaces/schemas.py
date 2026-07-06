# apps/api/services/workspaces/schemas.py

"""Pydantic contracts for workspace, membership, and invitation routes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.user import User
from models.workspace import Workspace, WorkspaceInvitation, WorkspaceMembership, WorkspaceRole
from utils.validation import normalize_email, normalize_optional_text


class WorkspaceRead(BaseModel):
    id: UUID
    slug: str
    name: str
    icon_url: str | None = None
    is_personal: bool
    status: str
    current_user_role: WorkspaceRole | None = None
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_workspace(
        cls,
        workspace: Workspace,
        *,
        current_user_role: str | WorkspaceRole | None = None,
    ) -> "WorkspaceRead":
        data = cls.model_validate(workspace)
        if current_user_role is not None:
            data.current_user_role = WorkspaceRole(current_user_role)
        return data


class WorkspacesListResponse(BaseModel):
    workspaces: list[WorkspaceRead]
    total: int
    limit: int
    offset: int


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=3, max_length=100)

    @field_validator("name", "slug")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    slug: str | None = Field(default=None, min_length=3, max_length=100)

    @field_validator("name", "slug")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class WorkspaceMembershipRead(BaseModel):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    role: WorkspaceRole
    user_email: str | None = None
    user_display_name: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_membership(cls, membership: WorkspaceMembership) -> "WorkspaceMembershipRead":
        data = cls.model_validate(membership)
        user = getattr(membership, "user", None)
        if isinstance(user, User):
            data.user_email = user.email
            data.user_display_name = user.display_name
        return data


class WorkspaceMembershipsListResponse(BaseModel):
    memberships: list[WorkspaceMembershipRead]
    total: int
    limit: int
    offset: int


class WorkspaceMembershipCreateRequest(BaseModel):
    user_id: UUID
    role: WorkspaceRole = WorkspaceRole.MEMBER


class WorkspaceMembershipUpdateRequest(BaseModel):
    role: WorkspaceRole


class WorkspaceInvitationRead(BaseModel):
    id: UUID
    workspace_id: UUID
    email: str
    role: WorkspaceRole
    invited_by: UUID
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_invitation(cls, invitation: WorkspaceInvitation) -> "WorkspaceInvitationRead":
        return cls.model_validate(invitation)


class WorkspaceInvitationsListResponse(BaseModel):
    invitations: list[WorkspaceInvitationRead]
    total: int
    limit: int
    offset: int


class WorkspaceInvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: WorkspaceRole = WorkspaceRole.MEMBER
    expires_in_days: int = Field(default=7, ge=1, le=30)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class WorkspaceInvitationCreateResponse(BaseModel):
    invitation: WorkspaceInvitationRead
    token: str


class WorkspaceInvitationUpdateRequest(BaseModel):
    role: WorkspaceRole | None = None
    expires_at: datetime | None = None


class WorkspaceInvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=16, max_length=512)

    @field_validator("token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        return value.strip()


class WorkspaceInvitationAcceptResponse(BaseModel):
    workspace: WorkspaceRead
    membership: WorkspaceMembershipRead
    invitation: WorkspaceInvitationRead
    status: str
    message: str
