# apps/api/models/platform_ingestion_usage.py

"""Monthly platform ingestion admission counters."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, UniqueConstraint, text

from models.base import Base, TimestampMixin, UUIDMixin


class PlatformIngestionUsage(Base, UUIDMixin, TimestampMixin):
    """Tracks calls reserved before platform ingestion."""

    __tablename__ = "platform_ingestion_usage"

    period_month = Column(Date, nullable=False)
    requests_reserved = Column(BigInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(
            "requests_reserved >= 0",
            name="ck_platform_ingestion_usage_requests_nonnegative",
        ),
        UniqueConstraint("period_month", name="uq_platform_ingestion_usage_month"),
    )
