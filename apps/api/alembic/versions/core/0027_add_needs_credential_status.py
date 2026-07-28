"""add auth-mode-specific integration credential status

Revision ID: core_0027
Revises: core_0026
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0027"
down_revision: str | Sequence[str] | None = "core_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUS_CHECK = (
    "status IN ('auth_pending', 'discovery_pending', "
    "'needs_resource_selection', 'active', 'degraded', 'error', "
    "'revoked', 'needs_reauth')"
)
_NEW_STATUS_CHECK = (
    "status IN ('auth_pending', 'discovery_pending', "
    "'needs_resource_selection', 'active', 'degraded', 'error', "
    "'revoked', 'needs_reauth', 'needs_credential')"
)


def upgrade() -> None:
    """Apply schema changes."""
    op.drop_constraint(
        "ck_integration_connections_status",
        "integration_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_integration_connections_status",
        "integration_connections",
        _NEW_STATUS_CHECK,
    )
    op.execute(
        sa.text(
            """
            UPDATE integration_connections AS connection
            SET status = 'needs_credential'
            FROM external_credentials AS credential
            WHERE connection.credential_id = credential.id
              AND connection.status = 'needs_reauth'
              AND credential.auth_mode <> 'oauth'
            """
        )
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.execute(
        sa.text(
            """
            UPDATE integration_connections
            SET status = 'error'
            WHERE status = 'needs_credential'
            """
        )
    )
    op.drop_constraint(
        "ck_integration_connections_status",
        "integration_connections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_integration_connections_status",
        "integration_connections",
        _OLD_STATUS_CHECK,
    )
