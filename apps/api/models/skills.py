# apps/api/models/skills.py

"""
Skill database model definitions.

Skills are user-created instruction packages with compact discovery metadata,
raw instructions, and requestable documentation references.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from models.base import BaseModel


class Skill(BaseModel):
    """Workspace-scoped instruction package for agent workflows.

    Progressive disclosure:
    - metadata: name, human_name, description for discovery
    - instructions: raw guidance loaded when a skill is activated
    - documentation_refs: manifest entries for docs loaded on demand

    Storage paths for documentation:
    - {PRIVATE_BUCKET}/workspaces/{workspace_id}/skills/{skill_id}/
    """

    __tablename__ = "skills"

    # Identity (Level 1 - always loaded for semantic matching)
    name = Column(String(64), nullable=False, index=True)
    human_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)

    # Ownership — always scoped to a workspace (personal or team)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # Instructions loaded when the skill is activated.
    instructions = Column(Text, nullable=False)

    # Progressive Discovery Documentation (Level 3 - loaded as needed from Cloud Bucket provider)
    # Keys are semantic names, values contain both original + markdown paths
    # Example: {
    #   "quick_start": {"original": "QUICKSTART.pdf", "markdown": "QUICKSTART.md"},
    #   "api_reference": {"original": "REFERENCE.docx", "markdown": "REFERENCE.md"}
    # }
    # Agent can choose format: markdown for text context, original for sandbox processing
    documentation_refs = Column(
        JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb")
    )

    # Scripts (Level 3 - Future: requires sandbox integration)
    # Example: {"validate_input": "validate.py", "process_data": "process.py"}
    # script_refs = Column(JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb"))

    # Metadata for extensibility
    metadata_json = Column("metadata", JSONB, nullable=True)

    # Status
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_favorite = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner_workspace = relationship("Workspace", foreign_keys=[workspace_id])
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        # Unique name per workspace
        UniqueConstraint("workspace_id", "name", name="uq_skills_workspace_name"),
        # Workspace index
        Index(
            "idx_skills_workspace",
            "workspace_id",
        ),
        # Active skills index
        Index(
            "idx_skills_active",
            "is_active",
            postgresql_where=text("is_active = true"),
        ),
        # Workspace + created_at for listing
        Index("ix_skills_workspace_created", "workspace_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Skill id={self.id} name={self.name} active={self.is_active}>"
