# apps/api/integrations/airtable/tools/utils.py

"""Shared Airtable bindings, credential access, and mutation intent."""

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.audit_events import (
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.credentials import get_usable_connection_credential
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference

from ..client import AirtableClient

AIRTABLE_BINDING = IntegrationToolBinding(
    provider_keys=frozenset({"airtable"}),
    resource_types=frozenset({"airtable_base"}),
)
AIRTABLE_WRITE_BINDING = IntegrationToolBinding(
    provider_keys=AIRTABLE_BINDING.provider_keys,
    resource_types=AIRTABLE_BINDING.resource_types,
    requires_write=True,
)
RESULTS_FIELD = (ToolFieldPresentation(key="results", label="Bases", format="list"),)


async def airtable_client(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
) -> AirtableClient:
    return await airtable_client_for_principal(
        ctx.deps.db,
        actor=ctx.deps.user,
        workspace=ctx.deps.workspace,
        entry=entry,
    )


async def airtable_client_for_principal(
    db,
    *,
    actor,
    workspace,
    entry: ResolvedContextEntry,
) -> AirtableClient:
    async def access_token() -> str:
        credential = await get_usable_connection_credential(
            db,
            connection_id=entry.connection_id,
            actor=actor,
            workspace=workspace,
        )
        if credential.auth_mode != "api_key":
            raise ModelRetry("The Airtable connection needs to be reconnected.")
        token = await resolve_secret(
            db,
            SecretReference(
                provider=credential.secret_provider or "",
                name=credential.secret_name or "",
                version=credential.secret_version or "",
            ),
            workspace_id=workspace.id,
            actor_id=actor.id,
        )
        if not token.strip():
            raise ModelRetry("The Airtable connection needs to be reconnected.")
        return token

    return AirtableClient(access_token)


def pending_record_operation_detail(
    entry: ResolvedContextEntry,
    *,
    action: str,
    table: str,
    field_count: int,
    record_id: str | None = None,
) -> IntegrationOperationDetail:
    """Build bounded mutation intent without storing record content."""
    return IntegrationOperationDetail(
        target=IntegrationOperationTarget(
            entity_type="airtable_base",
            external_id=entry.external_id,
            display_name=entry.display_name,
            integration_resource_id=str(entry.integration_resource_id),
        ),
        changes=[
            IntegrationOperationChange(
                action=action,
                entity_type="airtable_record",
                external_ref=record_id,
                fields={"table": table[:255], "field_count": field_count},
            )
        ],
        counts=IntegrationOperationCounts(applied=0, skipped=0, failed=0),
    )
