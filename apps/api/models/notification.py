# apps/api/models/notification.py

"""
Notification model for in-app notifications with optional actions.

Supports both user-attached and email-only (pre-user) notifications.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID

from models.base import BaseModel


class Notification(BaseModel):
    __tablename__ = "notifications"

    # Recipient linkage
    recipient_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    target_email = Column(CITEXT, nullable=True, index=True)

    # Context
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    notification_type = Column(String, nullable=False, index=True)
    source = Column(String, nullable=True)

    # Content
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=True)
    actions = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))

    # State
    read_at = Column(DateTime(timezone=True), nullable=True, index=True)
    archived = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    actioned_at = Column(DateTime(timezone=True), nullable=True)
    action_taken = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_notifications_user_read", "recipient_user_id", "read_at"),
        Index("ix_notifications_user_created", "recipient_user_id", "created_at"),
        Index("ix_notifications_workspaces", "workspace_id"),
    )
