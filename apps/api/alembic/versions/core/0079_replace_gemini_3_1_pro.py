# apps/api/alembic/versions/core/0079_replace_gemini_3_1_pro.py

"""Moves saved Gemini 3.1 Pro selections to Gemini 4 Argon.

Revision ID: core_0079
Revises: core_0078
"""

from alembic import op

revision = "core_0079"
down_revision = "core_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE agents
        SET model = 'gemini-4-argon'
        WHERE (model_provider = 'google' OR model_provider IS NULL)
            AND model = 'gemini-3.1-pro'
    """)
    op.execute("""
        UPDATE workspaces
        SET default_model = 'gemini-4-argon'
        WHERE default_model_provider = 'google'
            AND default_model = 'gemini-3.1-pro'
    """)


def downgrade() -> None:
    # The original selection is lost, and restoring the retired model breaks direct runs.
    pass
