"""add audit rollup correlation index

Revision ID: core_0037
Revises: core_0036
Create Date: 2026-08-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0037"
down_revision: str | Sequence[str] | None = "core_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_audit_events_rollup_correlation"
_PARTIAL_PREDICATE = sa.text(
    "audit_rollup_run_id IS NOT NULL AND audit_rollup_tool_call_id IS NOT NULL"
)


def upgrade() -> None:
    """Materialize and index complete roll-up correlation keys."""
    op.add_column(
        "audit_events",
        sa.Column("audit_rollup_run_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("audit_rollup_tool_call_id", sa.Text(), nullable=True),
    )
    op.execute(
        """
        CREATE FUNCTION set_audit_event_rollup_correlation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.audit_rollup_run_id := NULLIF(NEW.details ->> 'run_id', '');
            NEW.audit_rollup_tool_call_id := NULLIF(
                CASE
                    WHEN NEW.resource_type = 'tool_call' THEN NEW.resource_id::text
                    WHEN NEW.resource_type = 'integration_resource'
                        THEN NEW.details ->> 'tool_call_id'
                END,
                ''
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER set_audit_event_rollup_correlation
        BEFORE INSERT OR UPDATE OF resource_type, resource_id, details
        ON audit_events
        FOR EACH ROW
        EXECUTE FUNCTION set_audit_event_rollup_correlation()
        """
    )
    op.execute(
        """
        UPDATE audit_events
        SET
            audit_rollup_run_id = NULLIF(details ->> 'run_id', ''),
            audit_rollup_tool_call_id = NULLIF(
                CASE
                    WHEN resource_type = 'tool_call' THEN resource_id::text
                    WHEN resource_type = 'integration_resource'
                        THEN details ->> 'tool_call_id'
                END,
                ''
            )
        WHERE
            NULLIF(details ->> 'run_id', '') IS NOT NULL
            AND NULLIF(
                CASE
                    WHEN resource_type = 'tool_call' THEN resource_id::text
                    WHEN resource_type = 'integration_resource'
                        THEN details ->> 'tool_call_id'
                END,
                ''
            ) IS NOT NULL
        """
    )
    with op.get_context().autocommit_block():
        op.create_index(
            _INDEX_NAME,
            "audit_events",
            [
                "workspace_id",
                "audit_rollup_run_id",
                "audit_rollup_tool_call_id",
            ],
            postgresql_concurrently=True,
            postgresql_where=_PARTIAL_PREDICATE,
        )


def downgrade() -> None:
    """Remove materialized audit roll-up correlation keys."""
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX_NAME,
            table_name="audit_events",
            postgresql_concurrently=True,
            postgresql_where=_PARTIAL_PREDICATE,
        )
    op.execute("DROP TRIGGER set_audit_event_rollup_correlation ON audit_events")
    op.execute("DROP FUNCTION set_audit_event_rollup_correlation()")
    op.drop_column("audit_events", "audit_rollup_tool_call_id")
    op.drop_column("audit_events", "audit_rollup_run_id")
