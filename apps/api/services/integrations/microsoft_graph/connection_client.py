# apps/api/services/integrations/microsoft_graph/connection_client.py

"""Build Microsoft Graph clients from persisted personal connections."""

from pydantic_ai import ModelRetry
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.integrations import IntegrationConnection
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.credentials import (
    build_personal_oauth_access_token_resolver,
    ensure_fresh_credential,
    get_usable_connection_credential,
)

from .client import MicrosoftGraphClient


def graph_client_for_connection(
    db: AsyncSession,
    connection: IntegrationConnection,
    *,
    expected_provider_key: str,
    send_errors: bool = False,
) -> MicrosoftGraphClient:
    """Create a paced Graph client from a visible personal connection.

    Set `send_errors` for a sender that paces itself, so throttling is reported as rejected.
    """
    access_token = build_personal_oauth_access_token_resolver(
        db,
        connection,
        expected_provider_key=expected_provider_key,
        refresh_token=refresh_oauth_credential,
        credential_error=lambda: _credential_error(connection, expected_provider_key),
        open_transaction_error=(
            "Microsoft Graph callers must close database transactions before I/O"
        ),
    )
    return MicrosoftGraphClient(
        access_token,
        provider_key=expected_provider_key,
        pacing_key=str(connection.id),
        send_errors=send_errors,
    )


def graph_client_for_principal(
    db: AsyncSession, *, actor, workspace, entry, provider_key: str, reconnect_message: str
) -> MicrosoftGraphClient:
    """Creates a paced Graph client that acts as the user for one active-context entry."""

    async def access_token(force: bool) -> str:
        usable = await get_usable_connection_credential(
            db, connection_id=entry.connection_id, actor=actor, workspace=workspace
        )
        credential = await ensure_fresh_credential(
            db, credential_id=usable.id, refresh_token=refresh_oauth_credential, force=force
        )
        if not credential.access_token:
            raise ModelRetry(reconnect_message)
        return credential.access_token

    return MicrosoftGraphClient(
        access_token, provider_key=provider_key, pacing_key=str(entry.connection_id)
    )


def _credential_error(
    connection: IntegrationConnection,
    provider_key: str,
) -> IntegrationAuthError:
    return IntegrationAuthError(
        "Microsoft Graph connection credentials are not available",
        provider_key=provider_key,
        connection_id=str(connection.id),
        operation="graph_client_for_connection",
    )
