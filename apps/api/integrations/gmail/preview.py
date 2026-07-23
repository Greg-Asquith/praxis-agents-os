# apps/api/integrations/gmail/preview.py

"""Gmail preview contribution for the generic integration preview route."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.integrations import IntegrationConnection
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.credentials import ensure_fresh_credential
from services.integrations.plugin import IntegrationPreviewPayload

from .client import GmailClient

PREVIEW_OPERATION = "preview_gmail_message"


async def fetch_message_preview(
    db: AsyncSession,
    connection: IntegrationConnection,
    ref: str,
) -> IntegrationPreviewPayload:
    """Fetch one raw Gmail message for engine-owned bounding and sanitization."""
    # Resolve at call time so provider operation tests can replace the transport
    # boundary without rebuilding the registered plugin.
    from .operations.preview_message import preview_message

    payload = await preview_message(_gmail_client(db, connection), message_id=ref)
    return IntegrationPreviewPayload(
        content_type="html" if payload.get("content_type") == "html" else "text",
        content=str(payload.get("content", "")),
        meta=dict(payload.get("meta") or {}),
    )


def _gmail_client(db: AsyncSession, connection: IntegrationConnection) -> GmailClient:
    async def access_token(force: bool) -> str:
        credential = await ensure_fresh_credential(
            db,
            credential_id=connection.credential_id,
            refresh_token=refresh_oauth_credential,
            force=force,
        )
        token = credential.access_token
        if not token:
            raise IntegrationAuthError(
                "The Gmail connection needs to be reconnected",
                provider_key="gmail",
                connection_id=str(connection.id),
                operation=PREVIEW_OPERATION,
            )
        return token

    return GmailClient(access_token)
