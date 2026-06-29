# apps/api/models/base.py

"""Base SQLAlchemy models and mixins."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, declared_attr
from sqlalchemy.sql import func

# SQLAlchemy Base class
Base = declarative_base()


class UUIDMixin:
    """Mixin to add UUID primary key to models."""

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamps to models."""

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """Mixin to add soft delete functionality to models."""

    deleted = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    @property
    def is_deleted(self):
        """Check if the model is soft deleted."""
        return self.deleted

    def soft_delete(self, deleted_by=None, cascade=True):
        """
        Mark the record as soft deleted.

        Args:
            cascade: If True, also soft delete related child records
        """
        self.deleted = True
        self.deleted_by = deleted_by
        self.deleted_at = datetime.now(UTC)

        if cascade:
            self._cascade_soft_delete()

    def restore(self, cascade=True):
        """
        Restore a soft deleted record.

        Args:
            cascade: If True, also restore related child records that were
                    soft deleted at the same time
        """
        if cascade:
            self._cascade_restore()

        self.deleted = False
        self.deleted_at = None
        self.deleted_by = None

    def _cascade_soft_delete(self):
        """
        Override in subclasses to define cascade behavior for soft delete.
        Called when soft_delete() is invoked with cascade=True.
        """

    def _cascade_restore(self):
        """
        Override in subclasses to define cascade behavior for restore.
        Called when restore() is invoked with cascade=True.
        """

    @classmethod
    def query(cls, include_deleted: bool = False):
        """
        Default query method that filters out soft-deleted records by default.

        Args:
            include_deleted: If True, include soft-deleted records

        Returns:
            SQLAlchemy select statement
        """
        stmt = select(cls)
        if not include_deleted:
            stmt = stmt.where(cls.deleted.is_(False))
        return stmt

    @classmethod
    def query_not_deleted(cls):
        """Query only non-deleted records."""
        return select(cls).where(cls.deleted.is_(False))

    @classmethod
    def query_with_deleted(cls):
        """Query all records including soft deleted ones."""
        return select(cls)

    @classmethod
    def query_only_deleted(cls):
        """Query only soft deleted records."""
        return select(cls).where(cls.deleted.is_(True))


def _camel_to_snake(name: str) -> str:
    """Convert a CamelCase class name to a snake_case table name."""
    name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()


class CreatedAtMixin:
    """Mixin that adds only a created_at timestamp — for append-only tables."""

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BaseModel(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Base model class with UUID primary key, timestamps, and soft delete."""

    __abstract__ = True

    @declared_attr
    def __tablename__(cls):
        """Generate table name from class name."""
        return _camel_to_snake(cls.__name__)


class AppModel(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """
    Base model for application-specific tables in the 'app' schema.

    Use this for custom domain tables that extend the core template.
    These tables are managed by app-specific migrations in alembic/versions/app/

    Example:
        class CandidateProfile(AppModel):
            __tablename__ = "candidate_profiles"

            entity_id = Column(UUID, ForeignKey("public.knowledge_entities.id"))
            resume_url = Column(String)
            linkedin_url = Column(String)
    """

    __abstract__ = True

    @declared_attr
    def __table_args__(cls):
        """Set table to use the 'app' schema."""
        return {"schema": "app"}

    @declared_attr
    def __tablename__(cls):
        """Generate table name from class name."""
        return _camel_to_snake(cls.__name__)
