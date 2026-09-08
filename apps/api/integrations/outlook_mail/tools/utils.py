# apps/api/integrations/outlook_mail/tools/utils.py

"""Outlook context binding, credentials, and bounded result helpers."""

from pydantic_ai import ModelRetry
from pydantic_core import to_json

from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)
from services.integrations.microsoft_graph import MicrosoftGraphClient

from ..references import OutlookMessageReference
from ..settings import outlook_mail_settings

OUTLOOK_MAIL_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"outlook_mail"}), resource_types=frozenset({"outlook_mailbox"})
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Mailboxes", format="list"),)
MAX_RESULT_BYTES = 768 * 1024


def bounded_output(results) -> dict:
    output = {"results": serialize_fan_out_results(results)}
    if len(to_json(output)) > MAX_RESULT_BYTES:
        raise ModelRetry("Outlook returned too much data. Select fewer mailboxes or fewer results.")
    return output


async def mailbox_client(ctx, entry) -> MicrosoftGraphClient:
    return await mailbox_client_for_principal(
        ctx.deps.db, actor=ctx.deps.user, workspace=ctx.deps.workspace, entry=entry
    )


async def mailbox_client_for_principal(db, *, actor, workspace, entry) -> MicrosoftGraphClient:
    async def access_token(force: bool) -> str:
        usable = await get_usable_connection_credential(
            db, connection_id=entry.connection_id, actor=actor, workspace=workspace
        )
        credential = await ensure_fresh_credential(
            db, credential_id=usable.id, refresh_token=refresh_oauth_credential, force=force
        )
        if not credential.access_token:
            raise ModelRetry("The Outlook connection needs to be reconnected.")
        return credential.access_token

    return MicrosoftGraphClient(
        access_token, provider_key="outlook_mail", pacing_key=str(entry.connection_id)
    )


def outlook_mail_available() -> bool:
    return bool(outlook_mail_settings.OUTLOOK_MAIL_OAUTH_CLIENT_ID.strip())


def mailbox_time_zone(entry) -> str | None:
    value = entry.permissions_metadata.get("time_zone")
    return value[:100] if isinstance(value, str) else None


def message_result(entry, message: dict) -> dict:
    message_id = message["message_id"]
    return {key: value for key, value in message.items() if key != "message_id"} | {
        "reference": OutlookMessageReference(
            mailbox_id=entry.external_id, message_id=message_id, label="Outlook message"
        )
    }
