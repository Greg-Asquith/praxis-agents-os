# apps/api/integrations/sharepoint/tools/utils.py

"""SharePoint context binding, credentials, and complete result bounds."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import replace

from pydantic_ai import ModelRetry
from pydantic_core import to_json

from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.agents.runtime.untrusted import UntrustedNode
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
from services.integrations.microsoft_graph import MicrosoftGraphClient

from ..operations.link_utils import direct_link_path
from ..settings import sharepoint_settings

SHAREPOINT_DRIVE_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"sharepoint"}), resource_types=frozenset({"sharepoint_drive"})
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Libraries", format="list"),)
MAX_RESULT_BYTES = 768 * 1024


def bounded_output(results) -> dict:
    output = {"results": serialize_fan_out_results(results)}
    if len(to_json(output)) > MAX_RESULT_BYTES:
        raise ModelRetry("SharePoint returned too much data. Select fewer libraries or results.")
    return output


async def drive_client(ctx, entry) -> MicrosoftGraphClient:
    return await drive_client_for_principal(
        ctx.deps.db, actor=ctx.deps.user, workspace=ctx.deps.workspace, entry=entry
    )


async def drive_client_for_principal(db, *, actor, workspace, entry) -> MicrosoftGraphClient:
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
        if not credential.access_token:
            raise ModelRetry("The SharePoint connection needs to be reconnected.")
        return credential.access_token

    return MicrosoftGraphClient(
        access_token, provider_key="sharepoint", pacing_key=str(entry.connection_id)
    )


def sharepoint_available() -> bool:
    return bool(sharepoint_settings.SHAREPOINT_OAUTH_CLIENT_ID.strip())


def link_connection_entries(ctx) -> list[list[ResolvedContextEntry]]:
    """Groups selected libraries without choosing between ambiguous drive scopes."""
    active = ctx.deps.active_context
    entries = active.compatible_entries(SHAREPOINT_DRIVE_BINDING) if active else ()
    if not entries:
        raise ModelRetry("Select a SharePoint library in Active Context, then try the link again.")
    if any(count != 1 for count in Counter(entry.external_id for entry in entries).values()):
        raise ModelRetry("Select each SharePoint library once, then try the link again.")
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry.connection_id].append(entry)
    return list(grouped.values())


def link_request_groups(
    ctx, url: str
) -> list[tuple[ResolvedContextEntry, list[ResolvedContextEntry]]]:
    """Selects request connections and their audit libraries before credentials."""
    groups = link_connection_entries(ctx)
    urls = link_drive_urls(entry for entries in groups for entry in entries)
    direct = direct_link_path(url, urls)
    if direct:
        return [
            (entry, entries)
            for entries in groups
            for entry in entries
            if entry.external_id == direct[0]
        ]
    return [(entries[0], entries) for entries in groups]


def link_drive_urls(entries: Iterable[ResolvedContextEntry]) -> dict[str, str]:
    """Retains every selected drive even when its cached URL is unavailable."""
    return {
        entry.external_id: str(entry.permissions_metadata.get("web_url") or "") for entry in entries
    }


def reconcile_link_result(
    result: IntegrationContextResult,
    entries: list[ResolvedContextEntry],
    recovery: dict[str, UntrustedNode],
) -> IntegrationContextResult:
    """Retains the resolved library or the failed connection's bounded hint."""
    if result.status == "success":
        selected = next(
            entry for entry in entries if entry.external_id == result.data["reference"].drive_id
        )
        return replace(result, entry=selected)
    if recovery:
        return replace(result, data=recovery)
    return result
