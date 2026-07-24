# apps/api/models/embedding_usage.py

"""Monthly workspace embedding-token usage counters."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, TimestampMixin, UUIDMixin


class EmbeddingTokenUsage(Base, UUIDMixin, TimestampMixin):
    """Track embedding tokens consumed by a workspace in one UTC month."""

    __tablename__ = "embedding_token_usage"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_month = Column(Date, nullable=False)
    tokens_used = Column(BigInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(
            "tokens_used >= 0",
            name="ck_embedding_token_usage_tokens_nonnegative",
        ),
        UniqueConstraint(
            "workspace_id",
            "period_month",
            name="uq_embedding_token_usage_workspace_month",
        ),
    )
