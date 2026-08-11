# apps/api/integrations/gmail/tools/utils.py

"""Shared Gmail tool bindings and credential access."""

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    IntegrationToolBinding,
    ToolFieldPresentation,
)
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)

from ..client import GmailClient
from ..settings import gmail_settings

GMAIL_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"gmail"}),
    resource_types=frozenset({"gmail_mailbox"}),
)
GMAIL_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=GMAIL_BINDING.provider_keys,
    resource_types=GMAIL_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Mailboxes", format="list"),)


async def gmail_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> GmailClient:
    return await gmail_client_for_principal(
        ctx.deps.db,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
        entry=entry,
    )


async def gmail_client_for_principal(
    db, *, actor, workspace, entry: ResolvedContextEntry
) -> GmailClient:
    async def access_token(force: bool) -> str:
        usable = await get_usable_connection_credential(
            db,
            connection_id=entry.connection_id,
            actor=actor,
            workspace=workspace,
        )
        credential = await ensure_fresh_credential(
            db,
            credential_id=usable.id,
            refresh_token=refresh_oauth_credential,
            force=force,
        )
        token = credential.access_token
        if not token:
            raise ModelRetry("The Gmail connection needs to be reconnected.")
        return token

    return GmailClient(access_token)


def gmail_available() -> bool:
    return bool(gmail_settings.GMAIL_OAUTH_CLIENT_ID.strip())
