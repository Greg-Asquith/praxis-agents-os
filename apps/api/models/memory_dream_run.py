# apps/api/models/memory_dream_run.py

"""One background pass that learns from a workspace's finished conversations."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base, TimestampMixin, UUIDMixin


class MemoryDreamRun(Base, UUIDMixin, TimestampMixin):
    """A dream over one workspace, advanced one state per job.

    Status moves are listed in `services/memories/dream/domain.py`. The newest completed
    run's `window_end` is the workspace watermark.
    """

    __tablename__ = "memory_dream_runs"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(16), nullable=False, server_default=text("'collecting'"))
    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=False)
    # Each conversation read, its visibility and owner, and the message sequences read.
    conversations = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    batch_handles = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Scope keys already applied, so a repeated apply job writes nothing twice.
    applied_scopes = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    operation_counts = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    usage_totals = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_code = Column(String(64), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('collecting', 'extracting', 'consolidating', 'applying', "
            "'completed', 'failed')",
            name="ck_memory_dream_runs_status",
        ),
        CheckConstraint(
            "(status IN ('completed', 'failed')) = (finished_at IS NOT NULL)",
            name="ck_memory_dream_runs_finished",
        ),
        CheckConstraint(
            "window_start IS NULL OR window_start <= window_end",
            name="ck_memory_dream_runs_window",
        ),
        # One unfinished dream per workspace, so two schedulers can't start a second.
        Index(
            "uq_memory_dream_runs_active_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("status NOT IN ('completed', 'failed')"),
        ),
        Index(
            "ix_memory_dream_runs_workspace_window",
            "workspace_id",
            "window_end",
            postgresql_where=text("status = 'completed'"),
        ),
    )
