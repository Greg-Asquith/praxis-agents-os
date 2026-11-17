# apps/api/models/media_generation.py

"""The record of each paid media generation call, written before the provider call."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, TimestampMixin, UUIDMixin


class MediaGeneration(Base, UUIDMixin, TimestampMixin):
    """One paid generation, keyed by the tool call that asked for it.

    ``requested`` is committed before the provider call, ``running`` once the
    provider's ID is known, so a stopped worker leaves a charge someone can find.
    """

    __tablename__ = "media_generations"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    run_id = Column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id = Column(String(128), nullable=False)
    task = Column(String(32), nullable=False)
    media_model = Column(String(64), nullable=False)
    route = Column(String(16), nullable=False)
    provider_model = Column(String(128), nullable=False)
    external_id = Column(String(512), nullable=True)
    status = Column(String(16), nullable=False)
    error = Column(String(500), nullable=True)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True)
    revision_id = Column(
        UUID(as_uuid=True), ForeignKey("file_revisions.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("run_id", "tool_call_id", name="uq_media_generations_run_tool_call"),
        CheckConstraint(
            "status IN ('requested', 'running', 'saved', 'failed')",
            name="ck_media_generations_status",
        ),
        CheckConstraint(
            "status <> 'saved' OR revision_id IS NOT NULL",
            name="ck_media_generations_saved_revision",
        ),
        Index("ix_media_generations_workspace_created", "workspace_id", "created_at"),
        Index("ix_media_generations_file_id", "file_id"),
        Index("ix_media_generations_revision_id", "revision_id"),
    )
