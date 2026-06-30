# apps/api/models/agent.py

"""
Agent models for saving config & scheduling.

Agents are separate entities with their own model/instructions configuration.
They can use both hardcoded tools AND user-created skills.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from models.base import BaseModel


class Agent(BaseModel):
    """Agent with instructions, tools, and skills.

    Agents are separate entities that can be delegated complex tasks.
    Unlike skills (which inject into the current agent), agents run
    as entirely separate entities with their own model and configuration.
    """

    __tablename__ = "agents"

    # Identity
    name = Column(String, nullable=False, index=True)
    slug = Column(
        String(100), nullable=False, index=True
    )  # Unique per user/workspace scope, not globally
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=False)

    # Ownership — always scoped to a workspace (personal or team)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # Direct tool access (hardcoded tool names)
    tool_names = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    # Tool policies: {tool_name: 'auto' | 'approval'}
    tool_policies = Column(JSONB, nullable=True)

    # Skill access (IDs of user-created skills this agent can use)
    skill_ids = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))

    # Agent collaboration (IDs of agents this agent can call)
    allowed_agent_ids = Column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # Agent configuration
    model_provider = Column(String(50), nullable=True)  # Override default provider
    model = Column(String(100), nullable=True)  # Override default model
    model_settings = Column(
        JSONB, nullable=True
    )  # Provider-specific settings (reasoning effort, thinking budget)
    azure_deployment = Column(
        String(100), nullable=True
    )  # Azure OpenAI deployment name (special case)
    max_steps = Column(Integer, nullable=True, default=20, server_default=text("20"))

    # Status & tracking
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_favorite = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)

    # Relationships
    owner_workspace = relationship("Workspace", foreign_keys=[workspace_id])
    creator = relationship("User", foreign_keys=[created_by])
    schedules = relationship("AgentSchedule", back_populates="agent", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_agents_workspace_created", "workspace_id", "created_at"),
        Index("ix_agents_name_workspace", "name", "workspace_id"),
        # Slug uniqueness scoped per workspace
        Index(
            "ix_agents_slug_workspace",
            "slug",
            "workspace_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<Agent id={self.id} name={self.name} active={self.is_active}>"


class AgentSchedule(BaseModel):
    """Scheduled agent configurations for automated runs."""

    __tablename__ = "agent_schedules"

    # Core relationships
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )

    # Schedule configuration
    schedule_type = Column(String, nullable=False)
    cron_expression = Column(String, nullable=True)
    interval_minutes = Column(Integer, nullable=True)
    run_once_at = Column(DateTime(timezone=True), nullable=True)
    # IANA zone for cron wall-clock evaluation (ignored by interval/once).
    timezone = Column(String(64), nullable=False, default="UTC", server_default=text("'UTC'"))

    # Context for execution
    default_prompt = Column(Text, nullable=True)
    execution_params = Column(JSONB, nullable=True)

    # Active Context for scheduled runs.
    # Format: {type: 'resource', integration_resource_id: uuid} or {type: 'context_group', context_group_id: uuid}
    active_context = Column(JSONB, nullable=True)

    # Schedule state
    is_active = Column(Boolean, default=True, nullable=False, server_default=text("true"))
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    agent = relationship("Agent", back_populates="schedules")
    user = relationship("User", foreign_keys=[user_id])
    workspace = relationship("Workspace", foreign_keys=[workspace_id])
    runs = relationship("AgentScheduleRun", back_populates="schedule", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "schedule_type IN ('cron', 'interval', 'once')",
            name="agent_schedules_schedule_type_check",
        ),
        Index(
            "ix_agent_schedules_workspace_active",
            "workspace_id",
            "is_active",
            "created_at",
            postgresql_where=text("deleted = false"),
        ),
    )


class AgentScheduleRun(BaseModel):
    """Durable scheduled run attempt for one schedule fire time."""

    __tablename__ = "agent_schedule_runs"

    schedule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    attempt_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    status = Column(String(32), nullable=False, default="pending", server_default=text("'pending'"))

    claim_token = Column(UUID(as_uuid=True), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)
    service_token_jti = Column(UUID(as_uuid=True), nullable=True)

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(64), nullable=True)
    last_error_message = Column(Text, nullable=True)

    schedule = relationship("AgentSchedule", back_populates="runs")
    workspace = relationship("Workspace", foreign_keys=[workspace_id])
    user = relationship("User", foreign_keys=[user_id])
    agent = relationship("Agent", foreign_keys=[agent_id])
    conversation = relationship("Conversation", foreign_keys=[conversation_id])
    agent_run = relationship("AgentRun", foreign_keys=[agent_run_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending', 'claimed', 'accepted', 'running', 'awaiting_approval', "
            "'completed', 'retryable_failed', 'terminal_failed', 'cancelled'"
            ")",
            name="agent_schedule_runs_status_check",
        ),
        CheckConstraint("attempt_count >= 0", name="agent_schedule_runs_attempt_count_check"),
        UniqueConstraint(
            "schedule_id",
            "scheduled_for",
            name="uq_agent_schedule_runs_schedule_fire_time",
        ),
        Index(
            "ix_agent_schedule_runs_workspace_status_due",
            "workspace_id",
            "status",
            "scheduled_for",
            postgresql_where=text("deleted = false"),
        ),
        Index(
            "ix_agent_schedule_runs_claim_expiry",
            "status",
            "claim_expires_at",
            postgresql_where=text("deleted = false AND status = 'claimed'"),
        ),
        Index(
            "ix_agent_schedule_runs_schedule_created",
            "schedule_id",
            "created_at",
            postgresql_where=text("deleted = false"),
        ),
        Index(
            "ix_agent_schedule_runs_service_token_jti",
            "service_token_jti",
            unique=True,
            postgresql_where=text("service_token_jti IS NOT NULL"),
        ),
        Index(
            "ix_agent_schedule_runs_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("conversation_id IS NOT NULL"),
        ),
        Index(
            "ix_agent_schedule_runs_agent_run",
            "agent_run_id",
            unique=True,
            postgresql_where=text("agent_run_id IS NOT NULL"),
        ),
    )
