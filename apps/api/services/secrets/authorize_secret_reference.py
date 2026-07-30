# apps/api/services/secrets/authorize_secret_reference.py

"""Authorize a user-resolved secret reference for a workspace."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integrations import ExternalCredential, IntegrationConnection
from services.secrets.domain import SecretReference, belongs_to_workspace


async def authorize_secret_reference(
    db: AsyncSession,
    ref: SecretReference,
    *,
    workspace_id: UUID,
) -> None:
    """Allow workspace-namespaced references and same-workspace legacy bindings."""
    if belongs_to_workspace(ref, workspace_id):
        return

    existing_credential_id = await db.scalar(
        select(ExternalCredential.id)
        .join(
            IntegrationConnection,
            IntegrationConnection.credential_id == ExternalCredential.id,
        )
        .where(
            IntegrationConnection.owner_workspace_id == workspace_id,
            IntegrationConnection.deleted.is_(False),
            ExternalCredential.deleted.is_(False),
            ExternalCredential.secret_provider == ref.provider,
            ExternalCredential.secret_name == ref.name,
        )
        .limit(1)
    )
    if existing_credential_id is None:
        raise IntegrationValidationError(
            "Secret reference is not authorized for this workspace",
            provider_key=ref.provider,
            operation="resolve_secret",
        )
