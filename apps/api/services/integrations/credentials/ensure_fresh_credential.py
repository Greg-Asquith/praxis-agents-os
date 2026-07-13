# apps/api/services/integrations/credentials/ensure_fresh_credential.py

"""Serialize proactive OAuth refresh for a credential row."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import configure_async_db_session, get_async_db_session_factory
from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from core.settings import settings
from models.integrations import ExternalCredential, IntegrationConnection
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.credentials.utils import record_refresh_failure
from services.integrations.utils import (
    credential_encryption_key_id,
    ensure_credential_keys_loaded,
    record_integration_audit,
)

RefreshTokenFn = Callable[[ExternalCredential], Awaitable[dict[str, Any]]]


async def ensure_fresh_credential(
    db: AsyncSession,
    *,
    credential_id: UUID,
    refresh_token: RefreshTokenFn | None = None,
    force: bool = False,
) -> ExternalCredential:
    """Return a usable credential from an isolated, row-locked transaction.

    The OAuth connect slice supplies the provider-specific manifest-driven
    refresh callable once token endpoints and client settings exist. Refresh
    commits never include unrelated work pending on the caller's session.
    """
    await ensure_credential_keys_loaded(db)
    session_factory = get_async_db_session_factory()
    async with session_factory() as refresh_db:
        await configure_async_db_session(refresh_db)
        credential = await refresh_db.scalar(
            select(ExternalCredential)
            .where(ExternalCredential.id == credential_id, ExternalCredential.deleted.is_(False))
            .with_for_update()
        )
        if credential is None:
            raise IntegrationNotFoundError(
                "Integration credential not found",
                operation="ensure_fresh_credential",
            )
        if credential.revoked_at is not None:
            raise IntegrationAuthError(
                "Integration credential has been revoked",
                provider_key=credential.provider_key,
                operation="ensure_fresh_credential",
            )
        if not force and not _needs_refresh(credential):
            await refresh_db.commit()
            return credential

        connection = await refresh_db.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.credential_id == credential.id,
                IntegrationConnection.deleted.is_(False),
            )
        )
        try:
            if refresh_token is None:
                raise IntegrationAuthError(
                    "OAuth refresh is not configured for this provider",
                    provider_key=credential.provider_key,
                    operation="refresh_credential",
                )
            payload = await refresh_token(credential)
            access_token = payload.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise IntegrationAuthError(
                    "OAuth refresh did not return an access token",
                    provider_key=credential.provider_key,
                    operation="refresh_credential",
                )
            credential.access_token = access_token
            rotated_refresh = payload.get("refresh_token")
            if isinstance(rotated_refresh, str) and rotated_refresh:
                credential.refresh_token = rotated_refresh
            credential.token_type = payload.get("token_type") or credential.token_type
            expires_in = payload.get("expires_in")
            if isinstance(expires_in, (int, float)) and expires_in > 0:
                credential.token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            credential.encryption_key_id = credential_encryption_key_id()
            credential.last_refreshed_at = datetime.now(UTC)
            credential.refresh_failure_count = 0
            credential.last_refresh_error_code = None
            await refresh_db.flush()
            await record_integration_audit(
                refresh_db,
                workspace_id=connection.owner_workspace_id if connection else None,
                action=AuditAction.UPDATE,
                resource_type=AuditResourceType.INTEGRATION_CREDENTIAL,
                resource_id=credential.id,
                details={"provider_key": credential.provider_key, "refreshed": True},
            )
            await refresh_db.commit()
            return credential
        except (
            IntegrationAuthError,
            IntegrationPermissionError,
            IntegrationValidationError,
        ) as exc:
            await record_refresh_failure(
                refresh_db,
                credential,
                connection,
                exc,
                needs_reauth=True,
            )
            await refresh_db.commit()
            raise
        except IntegrationError as exc:
            await record_refresh_failure(
                refresh_db,
                credential,
                connection,
                exc,
                needs_reauth=False,
            )
            await refresh_db.commit()
            raise


def _needs_refresh(credential: ExternalCredential) -> bool:
    if credential.auth_mode != "oauth":
        return False
    if credential.access_token_encrypted is None:
        return credential.refresh_token_encrypted is not None
    if credential.token_expires_at is None:
        return False
    expires_at = credential.token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at - datetime.now(UTC) < timedelta(
        seconds=settings.INTEGRATIONS_TOKEN_REFRESH_LEEWAY_SECONDS
    )
