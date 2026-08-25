"""Add super-admin-managed platform skills.

Revision ID: core_0048
Revises: core_0047
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0048"
down_revision: str | Sequence[str] | None = "core_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_WORKSPACE_ID = "NULLIF(current_setting('app.current_workspace_id', true), '')::uuid"
_WORKSPACE_ROW = f"scope = 'workspace' AND workspace_id = {_ACTIVE_WORKSPACE_ID}"
_VISIBLE_ROW = f"{_ACTIVE_WORKSPACE_ID} IS NOT NULL AND ({_WORKSPACE_ROW} OR scope = 'platform')"


def _drop_skill_policies() -> None:
    for suffix in ("", "_select", "_insert", "_update", "_delete"):
        op.execute(sa.text(f'DROP POLICY IF EXISTS "skills_tenant_isolation{suffix}" ON "skills"'))


def upgrade() -> None:
    """Add platform scope and keep platform mutations outside the runtime role."""
    op.add_column(
        "skills",
        sa.Column("scope", sa.String(length=16), server_default="workspace", nullable=False),
    )
    op.alter_column("skills", "workspace_id", existing_type=sa.UUID(), nullable=True)
    op.create_check_constraint(
        "skills_scope_owner_check",
        "skills",
        "(scope = 'workspace' AND workspace_id IS NOT NULL) "
        "OR (scope = 'platform' AND workspace_id IS NULL)",
    )
    op.create_check_constraint(
        "skills_platform_content_check",
        "skills",
        "scope = 'workspace' OR "
        "(is_favorite = false AND COALESCE(documentation_refs, '{}'::jsonb) = '{}'::jsonb)",
    )
    op.create_index(
        "uq_skills_platform_name",
        "skills",
        ["name"],
        unique=True,
        postgresql_where=sa.text("scope = 'platform'"),
    )
    op.create_index(
        "idx_skills_platform_active",
        "skills",
        ["created_at"],
        postgresql_where=sa.text("scope = 'platform' AND is_active = true AND deleted = false"),
    )

    _drop_skill_policies()
    op.execute(
        sa.text(
            'CREATE POLICY "skills_tenant_isolation_select" ON "skills" '
            f"FOR SELECT USING ({_VISIBLE_ROW})"
        )
    )
    op.execute(
        sa.text(
            'CREATE POLICY "skills_tenant_isolation_insert" ON "skills" '
            f"FOR INSERT WITH CHECK ({_WORKSPACE_ROW})"
        )
    )
    op.execute(
        sa.text(
            'CREATE POLICY "skills_tenant_isolation_update" ON "skills" '
            f"FOR UPDATE USING ({_WORKSPACE_ROW}) WITH CHECK ({_WORKSPACE_ROW})"
        )
    )
    op.execute(
        sa.text(
            'CREATE POLICY "skills_tenant_isolation_delete" ON "skills" '
            f"FOR DELETE USING ({_WORKSPACE_ROW})"
        )
    )


def downgrade() -> None:
    """Remove platform skills and restore workspace-only ownership."""
    op.execute(sa.text("DELETE FROM skills WHERE scope = 'platform'"))
    _drop_skill_policies()
    predicate = f"workspace_id = {_ACTIVE_WORKSPACE_ID}"
    op.execute(
        sa.text(
            'CREATE POLICY "skills_tenant_isolation" ON "skills" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )
    op.drop_index("idx_skills_platform_active", table_name="skills")
    op.drop_index("uq_skills_platform_name", table_name="skills")
    op.drop_constraint("skills_platform_content_check", "skills", type_="check")
    op.drop_constraint("skills_scope_owner_check", "skills", type_="check")
    op.drop_column("skills", "scope")
    op.alter_column("skills", "workspace_id", existing_type=sa.UUID(), nullable=False)
