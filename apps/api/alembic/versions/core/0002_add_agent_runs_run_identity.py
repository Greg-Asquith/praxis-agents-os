"""add agent_runs run identity

Revision ID: core_0002
Revises: core_0001
Create Date: 2026-06-30 13:51:24.166269
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'core_0002'
down_revision: str | Sequence[str] | None = 'core_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_SCHEDULE_RUN_AGENT_RUN = 'fk_agent_schedule_runs_agent_run_id_agent_runs'


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        'agent_runs',
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('trigger', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('model_name', sa.String(length=128), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('input_tokens', sa.BigInteger(), nullable=True),
        sa.Column('input_tokens_cached', sa.BigInteger(), nullable=True),
        sa.Column('output_tokens', sa.BigInteger(), nullable=True),
        sa.Column('requests', sa.BigInteger(), nullable=True),
        sa.Column('tool_calls', sa.BigInteger(), nullable=True),
        sa.Column('usage_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled')",
            name='agent_runs_status_check',
        ),
        sa.CheckConstraint(
            "trigger IN ('interactive', 'scheduled')",
            name='agent_runs_trigger_check',
        ),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['deleted_by'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_runs_agent_id'), 'agent_runs', ['agent_id'], unique=False)
    op.create_index('ix_agent_runs_conversation_created', 'agent_runs', ['conversation_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_agent_runs_conversation_id'), 'agent_runs', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_agent_runs_deleted_at'), 'agent_runs', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_agent_runs_user_id'), 'agent_runs', ['user_id'], unique=False)
    op.create_index('ix_agent_runs_workspace_created', 'agent_runs', ['workspace_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_agent_runs_workspace_id'), 'agent_runs', ['workspace_id'], unique=False)
    op.create_index('ix_agent_runs_workspace_status', 'agent_runs', ['workspace_id', 'status'], unique=False, postgresql_where=sa.text('deleted = false'))

    op.add_column('agent_schedule_runs', sa.Column('agent_run_id', sa.UUID(), nullable=True))
    op.create_index('ix_agent_schedule_runs_agent_run', 'agent_schedule_runs', ['agent_run_id'], unique=True, postgresql_where=sa.text('agent_run_id IS NOT NULL'))
    op.create_foreign_key(
        FK_SCHEDULE_RUN_AGENT_RUN,
        'agent_schedule_runs',
        'agent_runs',
        ['agent_run_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_constraint(FK_SCHEDULE_RUN_AGENT_RUN, 'agent_schedule_runs', type_='foreignkey')
    op.drop_index('ix_agent_schedule_runs_agent_run', table_name='agent_schedule_runs', postgresql_where=sa.text('agent_run_id IS NOT NULL'))
    op.drop_column('agent_schedule_runs', 'agent_run_id')
    op.drop_index('ix_agent_runs_workspace_status', table_name='agent_runs', postgresql_where=sa.text('deleted = false'))
    op.drop_index(op.f('ix_agent_runs_workspace_id'), table_name='agent_runs')
    op.drop_index('ix_agent_runs_workspace_created', table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_user_id'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_deleted_at'), table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_conversation_id'), table_name='agent_runs')
    op.drop_index('ix_agent_runs_conversation_created', table_name='agent_runs')
    op.drop_index(op.f('ix_agent_runs_agent_id'), table_name='agent_runs')
    op.drop_table('agent_runs')
