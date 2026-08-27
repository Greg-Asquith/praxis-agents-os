# apps/api/integrations/notion/tools/utils.py

"""Shared Notion tool binding and credential access."""

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    IntegrationToolBinding,
    ToolFieldPresentation,
)
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import (
    IntegrationContextResult,
    serialize_fan_out_results,
)
from services.integrations.credentials import (
    ensure_fresh_credential,
    get_usable_connection_credential,
)

from ..client import NotionClient
from ..operations.utils import serialized_json_bytes
from ..settings import notion_settings

NOTION_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"notion"}),
    resource_types=frozenset({"notion_workspace"}),
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Workspaces", format="list"),)
MAX_NOTION_RESULT_BYTES = 768 * 1024


def bounded_notion_output(results: list[IntegrationContextResult]) -> dict[str, object]:
    """Returns a Notion result only when its complete serialized value is bounded."""
    output: dict[str, object] = {"results": serialize_fan_out_results(results)}
    if serialized_json_bytes(output) > MAX_NOTION_RESULT_BYTES:
        raise ModelRetry("Notion returned too much data. Retry with a lower maximum result count.")
    return output


async def notion_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> NotionClient:
    return await notion_client_for_principal(
        ctx.deps.db,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
        entry=entry,
    )


async def notion_client_for_principal(
    db, *, actor, workspace, entry: ResolvedContextEntry
) -> NotionClient:
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
            raise ModelRetry("The Notion connection needs to be reconnected.")
        return token

    return NotionClient(access_token, pacing_key=str(entry.connection_id))


def notion_available() -> bool:
    return bool(notion_settings.NOTION_OAUTH_CLIENT_ID.strip())
