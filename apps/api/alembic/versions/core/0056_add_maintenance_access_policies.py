"""Adds explicit maintenance access without requiring database superuser privileges.

Revision ID: core_0056
Revises: core_0055
"""

from collections.abc import Sequence

from alembic import op

revision: str = "core_0056"
down_revision: str | Sequence[str] | None = "core_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grants the migration account maintenance access to protected application tables."""
    op.execute("""
        DO $$
        DECLARE target record;
        BEGIN
            IF current_user = 'praxis_app'
               OR pg_has_role('praxis_app', current_user, 'MEMBER') THEN
                RAISE EXCEPTION 'Maintenance access requires a role unavailable to praxis_app';
            END IF;
            FOR target IN
                SELECT schemaname, tablename FROM pg_tables
                WHERE schemaname = 'public' AND rowsecurity
            LOOP
                EXECUTE format(
                    'CREATE POLICY maintenance_access ON %I.%I '
                    'FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true)',
                    target.schemaname, target.tablename
                );
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    """Removes the explicit maintenance policies while retaining tenant isolation."""
    op.execute("""
        DO $$
        DECLARE target record;
        BEGIN
            FOR target IN
                SELECT schemaname, tablename FROM pg_policies
                WHERE schemaname = 'public' AND policyname = 'maintenance_access'
            LOOP
                EXECUTE format('DROP POLICY maintenance_access ON %I.%I',
                               target.schemaname, target.tablename);
            END LOOP;
        END $$;
    """)
