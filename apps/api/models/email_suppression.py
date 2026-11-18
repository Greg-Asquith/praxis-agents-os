# apps/api/models/email_suppression.py

"""The workspace Do Not Email list, which every email send path checks."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, UUIDMixin

EMAIL_SUPPRESSION_REASON_MAX_CHARS = 500


class WorkspaceEmailSuppression(Base, UUIDMixin):
    """One address that no agent in the workspace may email. Entries are never edited."""

    __tablename__ = "workspace_email_suppressions"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # The address as entered, stripped and lower-cased.
    email = Column(String(320), nullable=False)
    # What sends are checked against: the address without a plus-tag or Gmail's ignored dots.
    match_key = Column(String(320), nullable=False)
    reason = Column(String(EMAIL_SUPPRESSION_REASON_MAX_CHARS), nullable=False)
    source = Column(String(16), nullable=False, server_default=text("'manual'"))
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "match_key", name="uq_workspace_email_suppressions_match_key"
        ),
        CheckConstraint(
            "email = lower(btrim(email)) AND length(email) >= 3",
            name="ck_workspace_email_suppressions_email",
        ),
        CheckConstraint(
            "length(btrim(reason)) >= 1", name="ck_workspace_email_suppressions_reason"
        ),
        CheckConstraint("source IN ('manual')", name="ck_workspace_email_suppressions_source"),
        Index("ix_workspace_email_suppressions_workspace_created", "workspace_id", "created_at"),
    )
