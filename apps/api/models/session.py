# apps/api/models/session.py

"""
Session models for tracking user sessions and authentication.

These models live in the public schema and handle:
- User sessions
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from models.base import BaseModel


class Session(BaseModel):
    __tablename__ = "sessions"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash = Column(
        String, unique=True, nullable=False, index=True
    )  # SHA256 hash of session token
    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_accessed = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    twofa_verified = Column(
        Boolean, default=False, nullable=False, server_default=text("false"), index=True
    )  # False for partial sessions awaiting 2FA

    # Composite indexes for performance optimisation
    __table_args__ = (
        Index("ix_sessions_user_expires", "user_id", "expires_at"),  # For user session queries
        Index(
            "ix_sessions_user_accessed", "user_id", "last_accessed"
        ),  # For user activity tracking
        Index("ix_sessions_ip_accessed", "ip_address", "last_accessed"),  # For security monitoring
        Index(
            "ix_sessions_expires_accessed", "expires_at", "last_accessed"
        ),  # For cleanup and analytics
        Index("ix_sessions_user_ip", "user_id", "ip_address"),  # For multi-IP detection
        Index(
            "ix_sessions_token_2fa", "token_hash", "twofa_verified"
        ),  # For 2FA session validation
    )

    # Relationships
    # Disambiguate multiple FKs to users (this model also has BaseModel.deleted_by)
    user = relationship("User", back_populates="sessions", foreign_keys=[user_id])
