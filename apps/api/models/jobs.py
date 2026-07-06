# apps/api/models/jobs.py

"""Generic background job queue model."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base, TimestampMixin, UUIDMixin


class Job(Base, UUIDMixin, TimestampMixin):
    """Durable generic background job row."""

    __tablename__ = "jobs"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True, index=True
    )
    kind = Column(String(64), nullable=False)
    subject_type = Column(String(64), nullable=True)
    subject_id = Column(UUID(as_uuid=True), nullable=True)
    content_hash = Column(String(64), nullable=False, server_default=text("''"))
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    priority = Column(Integer, nullable=False, server_default=text("100"))
    status = Column(String(16), nullable=False, server_default=text("'pending'"))
    run_after = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    max_attempts = Column(Integer, nullable=False, server_default=text("5"))
    locked_by = Column(String(255), nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    lock_expires_at = Column(DateTime(timezone=True), nullable=True)
    initiated_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    last_error_code = Column(String(64), nullable=True)
    last_error_message = Column(Text, nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="jobs_status_check",
        ),
        CheckConstraint("attempts >= 0", name="jobs_attempts_check"),
        CheckConstraint("max_attempts > 0", name="jobs_max_attempts_check"),
        Index(
            "ix_jobs_claim",
            "status",
            "run_after",
            "priority",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_jobs_reclaim",
            "status",
            "lock_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_jobs_workspace_status", "workspace_id", "status"),
        Index(
            "uq_jobs_in_flight",
            text("coalesce(workspace_id::text, '')"),
            text("kind"),
            text("coalesce(subject_type, '')"),
            text("coalesce(subject_id::text, '')"),
            text("content_hash"),
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )
