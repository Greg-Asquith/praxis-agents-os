# apps/api/models/agent_run.py

"""Generic agent run identity.

One durable execution record per agent turn — interactive or scheduled. This is the
universal `run_id` that approval/resume, usage, errors, audit correlation, and stream
replay all hang off. `agent_schedule_runs` remains the scheduler claim table and links
here via `agent_run_id` once a worker starts execution.
"""

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import relationship

from models.base import BaseModel


class AgentRun(BaseModel):
    """A single agent execution against a conversation."""

    __tablename__ = "agent_runs"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    parent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    delegation_depth = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    # How the run was triggered; status tracks its lifecycle.
    trigger = Column(String(32), nullable=False)
    status = Column(
        String(32), nullable=False, default="pending", server_default=text("'pending'")
    )

    # Resolved model identifier used for the run, for audit.
    model_name = Column(String(128), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    owner_instance_id = Column(String(128), nullable=True)

    # Hot usage columns for billing/audit queries; usage_json keeps the full RunUsage.
    input_tokens = Column(BigInteger, nullable=True)
    input_tokens_cached = Column(BigInteger, nullable=True)
    output_tokens = Column(BigInteger, nullable=True)
    requests = Column(BigInteger, nullable=True)
    tool_calls = Column(BigInteger, nullable=True)
    usage_json = Column(JSONB, nullable=True)

    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    metadata_json = Column("metadata", JSONB, nullable=True)

    conversation = relationship("Conversation", foreign_keys=[conversation_id])
    agent = relationship("Agent", foreign_keys=[agent_id])
    workspace = relationship("Workspace", foreign_keys=[workspace_id])
    user = relationship("User", foreign_keys=[user_id])
    parent_run = relationship(
        "AgentRun",
        remote_side="AgentRun.id",
        foreign_keys=[parent_run_id],
        back_populates="child_runs",
    )
    child_runs = relationship(
        "AgentRun",
        foreign_keys=[parent_run_id],
        back_populates="parent_run",
    )

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('interactive', 'scheduled', 'delegated')",
            name="agent_runs_trigger_check",
        ),
        CheckConstraint("delegation_depth >= 0", name="agent_runs_delegation_depth_check"),
        CheckConstraint(
            "status IN ("
            "'pending', 'running', 'awaiting_approval', "
            "'completed', 'failed', 'cancelled'"
            ")",
            name="agent_runs_status_check",
        ),
        Index("ix_agent_runs_conversation_created", "conversation_id", "created_at"),
        Index("ix_agent_runs_workspace_created", "workspace_id", "created_at"),
        Index(
            "ix_agent_runs_workspace_status",
            "workspace_id",
            "status",
            postgresql_where=text("deleted = false"),
        ),
        Index(
            "ix_agent_runs_lease_expiry",
            "lease_expires_at",
            postgresql_where=text("deleted = false AND status IN ('pending', 'running')"),
        ),
        Index(
            "ix_agent_runs_parent_created",
            "parent_run_id",
            "created_at",
            postgresql_where=text("parent_run_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} trigger={self.trigger} status={self.status}>"
