# apps/api/models/workspace_tool_settings.py

"""Workspace-level runtime tool availability and approval defaults."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, TimestampMixin, UUIDMixin


class WorkspaceToolSetting(Base, UUIDMixin, TimestampMixin):
    """An explicit workspace override for one runtime tool."""

    __tablename__ = "workspace_tool_settings"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    # Workspace default approval policy; null uses the tool definition's default.
    policy = Column(String(20), nullable=True)
    updated_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "tool_name",
            name="uq_workspace_tool_settings_workspace_tool",
        ),
        CheckConstraint(
            "policy IS NULL OR policy IN ('auto', 'approval')",
            name="ck_workspace_tool_settings_policy",
        ),
        Index(
            "ix_workspace_tool_settings_workspace_enabled",
            "workspace_id",
            "enabled",
        ),
    )
