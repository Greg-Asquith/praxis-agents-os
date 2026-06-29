# apps/api/models/security.py

"""Security event model."""

from sqlalchemy import Column, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.sql import func

from models.base import Base, CreatedAtMixin, UUIDMixin


class SecurityEvent(Base, UUIDMixin, CreatedAtMixin):
    """Append-only record of security-relevant activity."""

    __tablename__ = "security_events"

    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    event_type = Column(String(100), nullable=False, index=True)
    ip_address = Column(INET, nullable=False, index=True)
    endpoint = Column(String(500), nullable=True, index=True)
    user_email = Column(String(320), nullable=True, index=True)
    user_agent = Column(Text, nullable=True)
    details = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    request_id = Column(String(160), nullable=True, index=True)

    __table_args__ = (
        Index("ix_security_events_type_occurred", "event_type", "occurred_at"),
        Index("ix_security_events_ip_occurred", "ip_address", "occurred_at"),
        Index("ix_security_events_user_occurred", "user_email", "occurred_at"),
        Index("ix_security_events_details", "details", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<SecurityEvent {self.id}: {self.event_type}>"
