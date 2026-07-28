# apps/api/models/integration_table_schema.py

"""Provider-neutral cached table schemas for warehouse integrations."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base, UUIDMixin


class IntegrationTableSchema(Base, UUIDMixin):
    """Cached metadata for one table beneath an integration resource."""

    __tablename__ = "integration_table_schemas"

    resource_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_external_id = Column(String(1024), nullable=False)
    table_type = Column(String(32), nullable=False)
    description = Column(Text, nullable=True)
    schema_fields = Column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    partitioning = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    clustering_fields = Column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    row_count = Column(BigInteger, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    provider_last_modified_at = Column(DateTime(timezone=True), nullable=True)
    availability = Column(
        String(16),
        nullable=False,
        default="available",
        server_default=text("'available'"),
    )
    first_synced_at = Column(DateTime(timezone=True), nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "table_type IN ('table', 'view', 'materialized_view', 'external')",
            name="ck_integration_table_schemas_table_type",
        ),
        CheckConstraint(
            "availability IN ('available', 'removed')",
            name="ck_integration_table_schemas_availability",
        ),
        CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="ck_integration_table_schemas_row_count_nonnegative",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_integration_table_schemas_size_bytes_nonnegative",
        ),
        UniqueConstraint(
            "resource_id",
            "table_external_id",
            name="uq_integration_table_schemas_resource_table",
        ),
    )
