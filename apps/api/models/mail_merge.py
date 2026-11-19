# apps/api/models/mail_merge.py

"""Mail merges sent from a person's own mailbox, and one row per recipient."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base, TimestampMixin, UUIDMixin


class MailMerge(Base, UUIDMixin, TimestampMixin):
    """One approved merge, keyed by the tool call that proposed it.

    Counts come from the recipient rows (at most 500), so they can't drift from them.
    Status moves are listed in `services/mail_merge/domain.py`.
    """

    __tablename__ = "mail_merges"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Kept when the connection or run goes, so the sends still count against the budget.
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    tool_call_id = Column(String(128), nullable=False)
    provider_key = Column(String(64), nullable=False)
    sender_address = Column(String(320), nullable=False)
    subject_template = Column(Text, nullable=False)
    body_template = Column(Text, nullable=False)
    fallbacks = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    content_fingerprint = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, server_default=text("'queued'"))
    stop_reason = Column(String(32), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "tool_call_id", name="uq_mail_merges_run_tool_call"),
        CheckConstraint(
            "status IN ('queued', 'sending', 'paused', 'completed', 'cancelled', 'stopped')",
            name="ck_mail_merges_status",
        ),
        CheckConstraint(
            "provider_key IN ('gmail', 'outlook_mail')", name="ck_mail_merges_provider_key"
        ),
        # One merge sends from a mailbox at a time, which paces it without a shared lock.
        Index(
            "uq_mail_merges_active_connection",
            "connection_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'sending')"),
        ),
        Index("ix_mail_merges_workspace_created", "workspace_id", "created_at"),
    )


class MailMergeRecipient(Base, UUIDMixin):
    """One recipient of a merge, and what happened when it was sent to them.

    Status moves are listed in `services/mail_merge/domain.py`.
    """

    __tablename__ = "mail_merge_recipients"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    merge_id = Column(
        UUID(as_uuid=True), ForeignKey("mail_merges.id", ondelete="CASCADE"), nullable=False
    )
    position = Column(Integer, nullable=False)
    # Stripped and lower-cased, so the unique constraint catches case-only duplicates.
    email = Column(String(320), nullable=False)
    fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(16), nullable=False, server_default=text("'pending'"))
    message_id_header = Column(String(998), nullable=True)
    provider_message_id = Column(String(512), nullable=True)
    provider_draft_id = Column(String(512), nullable=True)
    # Gmail changes a draft's Message-ID on send but keeps its thread, so reconcile reads it.
    provider_thread_id = Column(String(512), nullable=True)
    error_code = Column(String(64), nullable=True)
    attempted_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("merge_id", "email", name="uq_mail_merge_recipients_email"),
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'unverified', 'skipped')",
            name="ck_mail_merge_recipients_status",
        ),
        CheckConstraint(
            "email = lower(btrim(email)) AND length(email) >= 3",
            name="ck_mail_merge_recipients_email",
        ),
        # Every row that reached the provider has an attempt time, so the budget counts it.
        CheckConstraint(
            "status IN ('pending', 'skipped') OR attempted_at IS NOT NULL",
            name="ck_mail_merge_recipients_attempted",
        ),
        Index("ix_mail_merge_recipients_merge_status", "merge_id", "status", "position"),
        Index("ix_mail_merge_recipients_workspace_attempted", "workspace_id", "attempted_at"),
    )


class MailMergeTestSend(Base, UUIDMixin):
    """One test email a person sent themselves from an approval card, before the merge exists.

    Tests count against the mailbox's daily budget like merge emails.
    """

    __tablename__ = "mail_merge_test_sends"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    tool_call_id = Column(String(128), nullable=False)
    content_fingerprint = Column(String(64), nullable=False)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_mail_merge_test_sends_connection_attempted", "connection_id", "attempted_at"),
        Index("ix_mail_merge_test_sends_run_tool_call", "run_id", "tool_call_id"),
    )
