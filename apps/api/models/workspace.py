# apps/api/models/workspace.py

"""Workspace, membership, and invitation models."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import relationship

from models.base import BaseModel
from utils.security import generate_invitation_token, hash_token, verify_token_hash


class WorkspaceRole(StrEnum):
    """User role within a workspace."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    READ_ONLY = "read_only"


# SQL fragment listing the valid roles, built from the enum to keep the
# CheckConstraints in sync with WorkspaceRole.
_ROLE_IN_SQL = "role IN ({})".format(", ".join(f"'{r.value}'" for r in WorkspaceRole))


class Workspace(BaseModel):
    __tablename__ = "workspaces"

    slug = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    icon_url = Column(String, nullable=True)
    is_personal = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    status = Column(String, default="active", nullable=False, server_default=text("'active'"))

    memberships = relationship(
        "WorkspaceMembership",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    invitations = relationship(
        "WorkspaceInvitation",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )

    def _cascade_soft_delete(self) -> None:
        """Soft delete memberships and pending invitations with the workspace."""
        for membership in self.memberships:
            if not membership.is_deleted:
                membership.soft_delete(cascade=False)

        for invitation in self.invitations:
            if not invitation.is_deleted:
                invitation.soft_delete(cascade=False)

    def _cascade_restore(self) -> None:
        """Restore memberships and invitations with the workspace."""
        for membership in self.memberships:
            if membership.is_deleted:
                membership.restore(cascade=False)

        for invitation in self.invitations:
            if invitation.is_deleted:
                invitation.restore(cascade=False)

    __table_args__ = (Index("ix_workspaces_status_created", "status", "created_at"),)


class WorkspaceMembership(BaseModel):
    __tablename__ = "workspace_memberships"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role = Column(
        String,
        nullable=False,
        default=WorkspaceRole.MEMBER.value,
        server_default=text(f"'{WorkspaceRole.MEMBER.value}'"),
    )

    workspace = relationship("Workspace", back_populates="memberships")
    user = relationship(
        "User",
        back_populates="workspace_memberships",
        foreign_keys=[user_id],
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        CheckConstraint(_ROLE_IN_SQL, name="workspace_memberships_role_check"),
        Index("ix_workspace_memberships_user_workspace", "user_id", "workspace_id"),
        Index("ix_workspace_memberships_role", "role"),
        Index("ix_workspace_memberships_created_at", "created_at"),
    )


class WorkspaceInvitation(BaseModel):
    __tablename__ = "workspace_invitations"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    email = Column(CITEXT, nullable=False)
    role = Column(
        String,
        nullable=False,
        default=WorkspaceRole.MEMBER.value,
        server_default=text(f"'{WorkspaceRole.MEMBER.value}'"),
    )
    invited_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    workspace = relationship("Workspace", back_populates="invitations")
    inviter = relationship("User", foreign_keys=[invited_by])

    @property
    def is_expired(self) -> bool:
        """Return whether the invitation has expired."""
        return datetime.now(UTC) > self.expires_at

    @property
    def is_accepted(self) -> bool:
        """Return whether the invitation has been accepted."""
        return self.accepted_at is not None

    @property
    def is_valid(self) -> bool:
        """Return whether the invitation can still be accepted."""
        return not self.is_expired and not self.is_accepted

    @classmethod
    def generate_token(cls) -> str:
        """Generate a secure raw invitation token."""
        return generate_invitation_token()

    @classmethod
    def hash_raw_token(cls, raw_token: str) -> str:
        """Hash a raw invitation token for secure at-rest storage."""
        return hash_token(raw_token)

    def verify_raw_token(self, raw_token: str) -> bool:
        """Constant-time verification of a raw token against the stored hash."""
        return verify_token_hash(raw_token, self.token_hash)

    __table_args__ = (
        CheckConstraint(_ROLE_IN_SQL, name="workspace_invitations_role_check"),
        # Prevent duplicate pending invitations for the same (workspace, email) pair
        Index(
            "uq_workspace_invitations_pending",
            "workspace_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND deleted = false"),
        ),
        Index("ix_workspace_invitations_workspace_email", "workspace_id", "email"),
        Index("ix_workspace_invitations_email_workspace", "email", "workspace_id"),
        Index("ix_workspace_invitations_role", "role"),
        Index("ix_workspace_invitations_created_at", "created_at"),
    )
