# apps/api/models/integration_context.py

"""Workspace-scoped integration context selections and reusable groups."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base, BaseModel, CreatedAtMixin, TimestampMixin, UUIDMixin


class IntegrationContextGroup(BaseModel):
    """A named workspace collection of integration resources."""

    __tablename__ = "integration_context_groups"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(120), nullable=False)
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    members = relationship(
        "IntegrationContextGroupMember",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index(
            "uq_integration_context_groups_workspace_name",
            "workspace_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted = false"),
        ),
    )


class IntegrationContextGroupMember(Base, UUIDMixin, CreatedAtMixin):
    """A hard-deleted resource membership in a context group."""

    __tablename__ = "integration_context_group_members"

    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_context_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    integration_resource_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    group = relationship("IntegrationContextGroup", back_populates="members")
    resource = relationship("IntegrationResource", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "integration_resource_id",
            name="uq_integration_context_group_members_resource",
        ),
    )


class ActiveContextSelection(Base, UUIDMixin, TimestampMixin):
    """One active integration context target per conversation."""

    __tablename__ = "active_context_selections"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    integration_resource_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_resources.id", ondelete="CASCADE"),
        nullable=True,
    )
    context_group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_context_groups.id", ondelete="CASCADE"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            name="uq_active_context_selections_conversation",
        ),
        CheckConstraint(
            "num_nonnulls(integration_resource_id, context_group_id) = 1",
            name="active_context_selections_target_check",
        ),
    )
