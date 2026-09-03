# apps/api/services/integrations/microsoft_graph/connection_client.py

"""Build Microsoft Graph clients from persisted personal connections."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.integrations import IntegrationConnection
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.credentials import build_personal_oauth_access_token_resolver

from .client import MicrosoftGraphClient


def graph_client_for_connection(
    db: AsyncSession,
    connection: IntegrationConnection,
    *,
    expected_provider_key: str,
) -> MicrosoftGraphClient:
    """Create a paced Graph client from a visible personal connection."""
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
