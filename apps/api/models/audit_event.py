# apps/api/models/audit_event.py

"""Workspace-scoped audit event model."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from models.base import Base, CreatedAtMixin, UUIDMixin


class AuditEvent(Base, UUIDMixin, CreatedAtMixin):
    """Append-only record of a business or system action."""

    __tablename__ = "audit_events"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(100), nullable=False, index=True)
    resource_id = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="success", server_default=text("'success'"))
    summary = Column(Text, nullable=False)
    tool_name = Column(String(100), nullable=True, index=True)
    tool_provider = Column(String(50), nullable=True)

    actor_type = Column(String(50), nullable=False)
    actor_id = Column(String(255), nullable=True)
    actor_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_display = Column(String(255), nullable=True)
    requested_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    details = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    request_id = Column(String(160), nullable=True, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_workspace_occurred", "workspace_id", "occurred_at"),
        Index(
            "ix_audit_events_workspace_tool_occurred",
            "workspace_id",
            "tool_name",
            "occurred_at",
        ),
        Index("ix_audit_events_actor_occurred", "actor_user_id", "occurred_at"),
        Index(
            "ix_audit_events_resource_occurred",
            "resource_type",
            "resource_id",
            "occurred_at",
        ),
        Index("ix_audit_events_status_occurred", "status", "occurred_at"),
        Index("ix_audit_events_details", "details", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.id}: {self.resource_type}.{self.action} {self.status}>"
