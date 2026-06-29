# apps/api/models/rate_limiting.py

"""
Rate limiting models for the Praxis Agents OS application.

These models live in the public schema and handle:
- Rate limit attempts tracking
"""

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET

from models.base import Base, TimestampMixin, UUIDMixin


class RateLimitAttempt(Base, UUIDMixin, TimestampMixin):
    """Track rate limiting attempts by IP address and endpoint."""

    __tablename__ = "rate_limit_attempts"

    # Core tracking fields
    ip_address = Column(INET, nullable=False, index=True)
    endpoint = Column(String, nullable=False, index=True)
    limit_type = Column(String, nullable=False)
    window_seconds = Column(Integer, nullable=False)
    attempts = Column(Integer, default=1, nullable=False, server_default=text("1"))
    window_start = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "ip_address",
            "endpoint",
            "limit_type",
            "window_seconds",
            "window_start",
            name="uq_rate_limit_attempt_bucket",
        ),
        Index("ix_rate_limit_cleanup", "created_at"),  # For cleanup queries
    )
