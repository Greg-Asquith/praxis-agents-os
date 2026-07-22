# apps/api/models/workspace_tool_settings.py

"""Workspace-level runtime tool availability settings."""

from sqlalchemy import Boolean, Column, ForeignKey, Index, String, UniqueConstraint, text
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
        Index(
            "ix_workspace_tool_settings_workspace_enabled",
            "workspace_id",
            "enabled",
        ),
    )
