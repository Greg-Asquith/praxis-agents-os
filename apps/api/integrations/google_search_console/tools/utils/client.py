# apps/api/integrations/google_search_console/tools/utils/client.py

"""Google Search Console runtime credential resolution and client construction."""

from pydantic_ai import ModelRetry, RunContext

from integrations.google_search_console.client import GoogleSearchConsoleClient
from integrations.google_search_console.settings import google_search_console_settings
from services.agents.runtime.context import RuntimeDeps
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)


async def google_search_console_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> GoogleSearchConsoleClient:
    return await google_search_console_client_for_principal(
        ctx.deps.db,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
        entry=entry,
    )


async def google_search_console_client_for_principal(
    db,
    *,
    actor,
    workspace,
    entry: ResolvedContextEntry,
) -> GoogleSearchConsoleClient:
    async def access_token(force: bool) -> str:
        credential = await get_usable_connection_credential(
            db,
            connection_id=entry.connection_id,
            actor=actor,
            workspace=workspace,
        )
        if credential.auth_mode != "oauth":
            raise ModelRetry(
                "The Google Search Console connection uses an unsupported credential type."
            )
        fresh = await ensure_fresh_credential(
            db,
            credential_id=credential.id,
            refresh_token=refresh_oauth_credential,
            force=force,
        )
        if not fresh.access_token:
            raise ModelRetry("The Google Search Console connection needs to be reconnected.")
        return fresh.access_token

    return GoogleSearchConsoleClient(access_token)


def google_search_console_indexing_available() -> bool:
    return google_search_console_settings.GOOGLE_SEARCH_CONSOLE_INDEXING_API_ENABLED
