# apps/api/models/embedding_usage.py

"""Monthly embedding-token usage counters with explicit ownership."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, TimestampMixin, UUIDMixin


class EmbeddingTokenUsage(Base, UUIDMixin, TimestampMixin):
    """Tracks embedding tokens consumed by an owner in one UTC month."""

    __tablename__ = "embedding_token_usage"

    scope = Column(String(16), nullable=False, server_default=text("'workspace'"))
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    period_month = Column(Date, nullable=False)
    tokens_used = Column(BigInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(
            "(scope = 'workspace' AND workspace_id IS NOT NULL) OR "
            "(scope = 'platform' AND workspace_id IS NULL)",
            name="embedding_token_usage_scope_owner_check",
        ),
        CheckConstraint(
            "tokens_used >= 0",
            name="ck_embedding_token_usage_tokens_nonnegative",
        ),
        Index(
            "uq_embedding_token_usage_platform_month",
            "period_month",
            unique=True,
            postgresql_where=text("scope = 'platform'"),
        ),
        UniqueConstraint(
            "workspace_id",
            "period_month",
            name="uq_embedding_token_usage_workspace_month",
        ),
    )
