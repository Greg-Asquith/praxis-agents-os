"""Moves saved Gemini 3.6 and 3.7 Flash selections to 3.8 Flash.

Revision ID: core_0065
Revises: core_0064
"""

from alembic import op

revision = "core_0065"
down_revision = "core_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE agents
        SET model = 'gemini-3.8-flash'
        WHERE (model_provider = 'google' OR model_provider IS NULL)
            AND model IN ('gemini-3.6-flash', 'gemini-3.7-flash')
    """)
    op.execute("""
        UPDATE workspaces
        SET default_model = 'gemini-3.8-flash'
        WHERE default_model_provider = 'google'
            AND default_model IN ('gemini-3.6-flash', 'gemini-3.7-flash')
    """)


def downgrade() -> None:
    # The original selection is lost, and restoring retired models breaks runs.
    pass
