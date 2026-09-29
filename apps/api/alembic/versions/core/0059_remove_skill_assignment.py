"""Removes per-agent skill assignment and skill favourites.

Revision ID: core_0059
Revises: core_0058
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0059"
down_revision = "core_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("agents", "skill_ids")
    op.drop_constraint("skills_platform_content_check", "skills", type_="check")
    op.drop_column("skills", "is_favorite")
    op.create_check_constraint(
        "skills_platform_content_check",
        "skills",
        "scope = 'workspace' OR COALESCE(documentation_refs, '{}'::jsonb) = '{}'::jsonb",
    )


def downgrade() -> None:
    op.drop_constraint("skills_platform_content_check", "skills", type_="check")
    op.add_column(
        "skills",
        sa.Column("is_favorite", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        "skills_platform_content_check",
        "skills",
        "scope = 'workspace' OR "
        "(is_favorite = false AND COALESCE(documentation_refs, '{}'::jsonb) = '{}'::jsonb)",
    )
    op.add_column(
        "agents",
        sa.Column(
            "skill_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
