# apps/api/models/integration_table_scope_rule.py

"""Provider-neutral row-scope rules for warehouse integration tables."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import BaseModel


class IntegrationTableScopeRule(BaseModel):
    """One connection-enforced row filter for a cached base table."""

    __tablename__ = "integration_table_scope_rules"

    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id = Column(
        UUID(as_uuid=True),
        ForeignKey("integration_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_external_id = Column(String(1024), nullable=False)
    column_name = Column(String(300), nullable=False)
    column_type = Column(String(16), nullable=False)
    allowed_values = Column(JSONB, nullable=False)
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "column_type IN ('string', 'integer')",
            name="ck_integration_table_scope_rules_column_type",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_values) = 'array' AND jsonb_array_length(allowed_values) > 0",
            name="ck_integration_table_scope_rules_allowed_values_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(table_external_id)) > 0",
            name="ck_integration_table_scope_rules_table_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(column_name)) > 0",
            name="ck_integration_table_scope_rules_column_not_blank",
        ),
        UniqueConstraint(
            "resource_id",
            "table_external_id",
            name="uq_integration_table_scope_rules_resource_table",
        ),
    )
