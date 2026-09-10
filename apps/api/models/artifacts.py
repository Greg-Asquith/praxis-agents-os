# apps/api/models/artifacts.py

"""Versioned agent-authored artifacts."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, BaseModel, CreatedAtMixin, TimestampMixin, UUIDMixin

ARTIFACT_TYPES = ("html", "markdown", "mermaid", "csv", "image-ref")
ARTIFACT_REVISION_KINDS = ("create", "edit", "restore")


class Artifact(BaseModel):
    """Artifact with explicit ownership and an immutable revision chain."""

    __tablename__ = "artifacts"

    scope = Column(String(16), nullable=False, server_default=text("'workspace'"))
    is_published = Column(Boolean, nullable=False, server_default=text("false"))
    published_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifact_revisions.id", use_alter=True, name="fk_artifacts_published_version"),
        nullable=True,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"))
    conversation_id = Column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"))
    current_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "artifact_revisions.id",
            use_alter=True,
            name="fk_artifacts_current_version",
        ),
        nullable=True,
        comment="Nullable only while inserting the initial revision.",
    )
    artifact_type = Column(String(16), nullable=False)
    title = Column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(scope = 'workspace' AND workspace_id IS NOT NULL) OR "
            "(scope = 'platform' AND workspace_id IS NULL)",
            name="artifacts_scope_owner_check",
        ),
        CheckConstraint(
            "scope = 'workspace' OR (agent_id IS NULL AND conversation_id IS NULL AND run_id IS NULL)",
            name="artifacts_platform_provenance_check",
        ),
        CheckConstraint(
            "scope = 'platform' OR is_published = false",
            name="artifacts_workspace_publication_check",
        ),
        Index(
            "ix_artifacts_platform_created",
            "created_at",
            postgresql_where=text("scope = 'platform' AND is_published = true AND deleted = false"),
        ),
        Index("ix_artifacts_published_version_id", "published_version_id"),
        CheckConstraint(
            "(scope = 'platform' OR published_version_id IS NULL) AND "
            "(NOT is_published OR published_version_id IS NOT NULL)",
            name="artifacts_published_pointer_check",
        ),
        CheckConstraint(
            f"artifact_type IN ({', '.join(repr(value) for value in ARTIFACT_TYPES)})",
            name="artifacts_type_check",
        ),
        Index(
            "ix_artifacts_workspace_created",
            "workspace_id",
            "created_at",
            postgresql_where=text("deleted = false"),
        ),
        Index("ix_artifacts_current_version_id", "current_version_id"),
        Index("ix_artifacts_agent_id", "agent_id"),
        Index("ix_artifacts_run_id", "run_id"),
    )


class ArtifactRevision(Base, UUIDMixin, CreatedAtMixin):
    """Append-only content revision for one artifact."""

    __tablename__ = "artifact_revisions"

    artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope = Column(String(16), nullable=False, server_default=text("'workspace'"))
    is_published = Column(Boolean, nullable=False, server_default=text("false"))
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_number = Column(Integer, nullable=False)
    revision_kind = Column(String(16), nullable=False)
    content_type = Column(String(128), nullable=False)
    extension = Column(String(16), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    content_hash = Column(String(64), nullable=False)
    object_key = Column(String(1024), nullable=False, unique=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    created_by_system = Column(Boolean, nullable=False, server_default=text("false"))
    restored_from_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifact_revisions.id"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "(scope = 'workspace' AND workspace_id IS NOT NULL) OR "
            "(scope = 'platform' AND workspace_id IS NULL)",
            name="artifact_revisions_scope_owner_check",
        ),
        CheckConstraint(
            "scope = 'platform' OR is_published = false",
            name="artifact_revisions_workspace_publication_check",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="artifact_revisions_revision_number_check",
        ),
        CheckConstraint(
            f"revision_kind IN ({', '.join(repr(value) for value in ARTIFACT_REVISION_KINDS)})",
            name="artifact_revisions_revision_kind_check",
        ),
        CheckConstraint(
            "size_bytes >= 0",
            name="artifact_revisions_size_bytes_check",
        ),
        CheckConstraint(
            "(CASE WHEN created_by_user_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_agent_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_system THEN 1 ELSE 0 END) = 1",
            name="artifact_revisions_exactly_one_actor_check",
        ),
        CheckConstraint(
            "(revision_kind = 'restore') = (restored_from_revision_id IS NOT NULL)",
            name="artifact_revisions_restore_source_check",
        ),
        UniqueConstraint(
            "artifact_id",
            "revision_number",
            name="uq_artifact_revisions_artifact_number",
        ),
        Index("ix_artifact_revisions_created_by_user_id", "created_by_user_id"),
        Index("ix_artifact_revisions_created_by_agent_id", "created_by_agent_id"),
        Index(
            "ix_artifact_revisions_restored_from_revision_id",
            "restored_from_revision_id",
        ),
    )


class ArtifactShare(Base, UUIDMixin, TimestampMixin):
    """Revocable, version-pinned anonymous access to an artifact."""

    __tablename__ = "artifact_shares"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifact_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    token_prefix = Column(String(8), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("access_count >= 0", name="artifact_shares_access_count_check"),
        Index("ix_artifact_shares_expires_at", "expires_at"),
        Index("ix_artifact_shares_workspace_created", "workspace_id", "created_at"),
    )


@event.listens_for(ArtifactRevision, "before_update")
def _reject_artifact_revision_mutation(_mapper, _connection, target: ArtifactRevision) -> None:
    """Allows publication without rewriting persisted artifact content."""
    state = inspect(target)
    if any(
        attribute.history.has_changes()
        and not (attribute.key == "is_published" and target.is_published is True)
        for attribute in state.attrs
    ):
        raise RuntimeError("Artifact revisions are immutable")
