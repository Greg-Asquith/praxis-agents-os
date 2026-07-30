# apps/api/services/integrations/credentials/get_usable_connection_credential.py

"""Load the currently usable credential for a visible connection."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError, IntegrationNotFoundError
from models.integrations import ExternalCredential, IntegrationConnection
from models.user import User
from models.workspace import Workspace
from services.integrations.domain import CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS


async def get_usable_connection_credential(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
) -> ExternalCredential:
    """Revalidate connection and credential state immediately before provider use."""
    visibility = (IntegrationConnection.owner_workspace_id == workspace.id) | (
        IntegrationConnection.owner_user_id == actor.id
    )
    row = (
        await db.execute(
            select(IntegrationConnection, ExternalCredential)
            .join(
                ExternalCredential,
                ExternalCredential.id == IntegrationConnection.credential_id,
            )
            .where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.deleted.is_(False),
                visibility,
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise IntegrationNotFoundError(
            "Integration connection not found",
            connection_id=str(connection_id),
            operation="get_usable_connection_credential",
        )

    connection, credential = row
    if (
        connection.status in CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS
        or credential.deleted
        or credential.revoked_at is not None
    ):
        raise IntegrationAuthError(
            "Integration connection credentials are not available",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="get_usable_connection_credential",
        )
    return credential
