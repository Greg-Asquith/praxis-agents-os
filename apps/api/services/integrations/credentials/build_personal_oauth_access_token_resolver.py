# apps/api/services/integrations/credentials/build_personal_oauth_access_token_resolver.py

"""Bind a personal integration connection to its OAuth access token."""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError, IntegrationNotFoundError
from models.integrations import ExternalCredential, IntegrationConnection
from services.integrations.credentials.ensure_fresh_credential import (
    RefreshTokenFn,
    ensure_fresh_credential,
)
from services.integrations.domain import CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS

AccessTokenResolver = Callable[[bool], Awaitable[str]]
CredentialErrorFactory = Callable[[], IntegrationAuthError]


def build_personal_oauth_access_token_resolver(
    db: AsyncSession,
    connection: IntegrationConnection,
    *,
    expected_provider_key: str,
    refresh_token: RefreshTokenFn,
    credential_error: CredentialErrorFactory,
    open_transaction_error: str,
) -> AccessTokenResolver:
    """Return a locked token resolver for one visible personal connection."""
    if (
        connection.provider_key != expected_provider_key
        or connection.deleted
        or connection.owner_user_id is None
        or connection.owner_workspace_id is not None
        or connection.status in CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS
    ):
        raise credential_error()
    if db.in_transaction():
        raise RuntimeError(open_transaction_error)

    async def access_token(force: bool) -> str:
        try:
            fresh = await ensure_fresh_credential(
                db,
                credential_id=connection.credential_id,
                refresh_token=refresh_token,
                force=force,
                expected_provider_key=expected_provider_key,
                expected_owner=(connection.owner_user_id, connection.owner_workspace_id),
            )
        except IntegrationNotFoundError as exc:
            raise credential_error() from exc
        _validate_credential_binding(
            fresh,
            connection=connection,
            expected_provider_key=expected_provider_key,
            credential_error=credential_error,
        )
        token = fresh.access_token
        if not token:
            raise credential_error()
        return token

    return access_token


def _validate_credential_binding(
    credential: ExternalCredential,
    *,
    connection: IntegrationConnection,
    expected_provider_key: str,
    credential_error: CredentialErrorFactory,
) -> None:
    if (
        credential.provider_key != expected_provider_key
        or credential.owner_user_id != connection.owner_user_id
        or credential.owner_workspace_id != connection.owner_workspace_id
    ):
        raise credential_error()
