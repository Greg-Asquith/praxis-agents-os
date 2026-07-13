# apps/api/services/integrations/credentials/find_duplicate_principals.py

"""Find live connections sharing an external-principal fingerprint."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import ExternalCredential, IntegrationConnection


async def find_duplicate_principals(
    db: AsyncSession,
    *,
    provider_key: str,
    principal_fingerprint: str,
    owner_user_id: UUID | None,
    owner_workspace_id: UUID | None,
    exclude_credential_id: UUID | None = None,
) -> list[UUID]:
    if (owner_user_id is None) == (owner_workspace_id is None):
        raise ValueError("Exactly one connection owner is required")
    stmt = (
        select(IntegrationConnection.id)
        .join(ExternalCredential, IntegrationConnection.credential_id == ExternalCredential.id)
        .where(
            IntegrationConnection.deleted.is_(False),
            ExternalCredential.deleted.is_(False),
            ExternalCredential.revoked_at.is_(None),
            ExternalCredential.provider_key == provider_key,
            ExternalCredential.principal_fingerprint == principal_fingerprint,
        )
    )
    if owner_user_id is not None:
        stmt = stmt.where(IntegrationConnection.owner_user_id == owner_user_id)
    else:
        stmt = stmt.where(IntegrationConnection.owner_workspace_id == owner_workspace_id)
    if exclude_credential_id is not None:
        stmt = stmt.where(ExternalCredential.id != exclude_credential_id)
    return list((await db.scalars(stmt)).all())
