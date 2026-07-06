# apps/api/models/files.py

"""File and file revision models."""

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
    Text,
    UniqueConstraint,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base, BaseModel, CreatedAtMixin, UUIDMixin

FILE_PROCESSING_STATUSES = ("pending", "processing", "ready", "error")
FILE_REVISION_KINDS = ("create", "edit", "replace", "restore", "import")
FILE_REFERENCE_TARGET_TYPES = ("conversation", "artifact", "agent", "schedule_run")

_REVISION_MUTABLE_ONCE = frozenset({"markdown_object_key", "markdown_size_bytes"})


def _in_sql(column_name: str, values: tuple[str, ...]) -> str:
    return f"{column_name} IN ({', '.join(repr(value) for value in values)})"


class File(BaseModel):
    """Workspace-scoped logical file with a current revision pointer."""

    __tablename__ = "files"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(32), nullable=False)
    content_type = Column(String(128), nullable=False)
    extension = Column(String(16), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, server_default=text("0"))
    content_hash = Column(String(64), nullable=False, server_default=text("''"))
    current_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("file_revisions.id", use_alter=True, name="fk_files_current_revision"),
        nullable=True,
        comment="Nullable only while inserting the initial revision.",
    )
    revision_count = Column(Integer, nullable=False, server_default=text("0"))
    processing_status = Column(String(16), nullable=False, server_default=text("'ready'"))
    processing_error = Column(Text, nullable=True)
    processing_attempts = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("revision_count >= 0", name="files_revision_count_check"),
        CheckConstraint(
            _in_sql("processing_status", FILE_PROCESSING_STATUSES),
            name="files_processing_status_check",
        ),
        CheckConstraint("processing_attempts >= 0", name="files_processing_attempts_check"),
        Index(
            "ix_files_workspace_created",
            "workspace_id",
            "created_at",
            postgresql_where=text("deleted = false"),
        ),
        Index(
            "ix_files_workspace_processing",
            "workspace_id",
            "processing_status",
            postgresql_where=text("deleted = false"),
        ),
    )


class FileRevision(Base, UUIDMixin, CreatedAtMixin):
    """Append-only file revision history."""

    __tablename__ = "file_revisions"

    file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    revision_kind = Column(String(16), nullable=False)
    content_type = Column(String(128), nullable=False)
    extension = Column(String(16), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    content_hash = Column(String(64), nullable=False)
    object_key = Column(String(1024), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    created_by_system = Column(Boolean, nullable=False, server_default=text("false"))
    restored_from_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("file_revisions.id"),
        nullable=True,
    )
    markdown_object_key = Column(String(1024), nullable=True)
    markdown_size_bytes = Column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint("revision_number > 0", name="file_revisions_revision_number_check"),
        CheckConstraint(
            _in_sql("revision_kind", FILE_REVISION_KINDS),
            name="file_revisions_revision_kind_check",
        ),
        CheckConstraint("size_bytes >= 0", name="file_revisions_size_bytes_check"),
        CheckConstraint(
            "(CASE WHEN created_by_user_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_agent_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_system THEN 1 ELSE 0 END) = 1",
            name="file_revisions_exactly_one_actor_check",
        ),
        CheckConstraint(
            "(revision_kind = 'restore') = (restored_from_revision_id IS NOT NULL)",
            name="file_revisions_restore_source_check",
        ),
        UniqueConstraint("file_id", "revision_number", name="uq_file_revisions_file_number"),
        Index("ix_file_revisions_workspace_hash", "workspace_id", "content_hash"),
    )


class FileReference(Base, UUIDMixin, CreatedAtMixin):
    """Non-copying attachment from a target resource to a file."""

    __tablename__ = "file_references"

    file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    target_type = Column(String(32), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    file_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("file_revisions.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            _in_sql("target_type", FILE_REFERENCE_TARGET_TYPES),
            name="file_references_target_type_check",
        ),
        UniqueConstraint(
            "file_id",
            "target_type",
            "target_id",
            name="uq_file_references_file_target",
        ),
        Index("ix_file_references_target", "target_type", "target_id"),
    )


class FileUpload(Base, UUIDMixin, CreatedAtMixin):
    """Ephemeral staging row for signed file uploads."""

    __tablename__ = "file_uploads"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    file_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        comment="No FK: new-file uploads are confirmed before the files row exists.",
    )
    revision_id = Column(UUID(as_uuid=True), nullable=False)
    object_key = Column(String(1024), nullable=False)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=False)
    declared_size_bytes = Column(BigInteger, nullable=False)
    declared_content_hash = Column(String(64), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("object_key", name="uq_file_uploads_object_key"),
        Index(
            "ix_file_uploads_pending_expiry",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )


@event.listens_for(FileRevision, "before_update")
def _reject_file_revision_mutation(_mapper, connection, target: FileRevision) -> None:
    """Reject revision rewrites except set-once derived markdown fields."""
    state = inspect(target)
    for attr in state.attrs:
        if not attr.history.has_changes():
            continue
        if attr.key not in _REVISION_MUTABLE_ONCE:
            raise RuntimeError(f"File revisions are immutable: {attr.key}")

        previous_value = next(iter(attr.history.deleted), None)
        if previous_value is None and target.id is not None and not attr.history.deleted:
            previous_value = connection.execute(
                select(getattr(FileRevision, attr.key)).where(FileRevision.id == target.id)
            ).scalar_one_or_none()
        if previous_value is not None:
            raise RuntimeError(f"File revision derived field is already set: {attr.key}")
