# apps/api/integrations/airtable/tools/utils.py

"""Shared Airtable bindings, credential access, and per-entry audit."""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import IntegrationToolBinding, ToolFieldPresentation
from services.audit_events import AuditStatus, record_integration_operation_audit_event
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


async def run_audited_operation(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    execute: Callable[[], Awaitable[Any]],
    external_ref: str | None = None,
    external_ref_from_result: Callable[[Any], str | None] | None = None,
) -> Any:
    try:
        result = await execute()
    except Exception as exc:
        await record_airtable_operation_audit(
            ctx,
            entry,
            tool_name=tool_name,
            operation=operation,
            status=AuditStatus.FAILURE,
            external_ref=external_ref,
            error_code=exc.__class__.__name__,
        )
        raise
    resolved_external_ref = (
        external_ref_from_result(result) if external_ref_from_result else external_ref
    )
    await record_airtable_operation_audit(
        ctx,
        entry,
        tool_name=tool_name,
        operation=operation,
        status=AuditStatus.SUCCESS,
        external_ref=resolved_external_ref,
    )
    return result


async def record_airtable_operation_audit(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    status: AuditStatus,
    external_ref: str | None = None,
    error_code: str | None = None,
) -> None:
    await record_integration_operation_audit_event(
        workspace_id=ctx.deps.workspace.id,
        agent=ctx.deps.agent,
        run=ctx.deps.run,
        tool_name=tool_name,
        provider_key="airtable",
        connection_id=entry.connection_id,
        integration_resource_id=entry.integration_resource_id,
        external_id=entry.external_id,
        operation=operation,
        status=status,
        external_ref=external_ref,
        error_code=error_code,
    )


def fan_out_dict(item) -> dict[str, Any]:
    return {
        "integration_resource_id": item.integration_resource_id,
        "connection_id": item.connection_id,
        "provider_key": item.provider_key,
        "external_id": item.external_id,
        "display_name": item.display_name,
        "status": item.status,
        "data": item.data,
        "error_code": item.error_code,
        "error_message": item.error_message,
    }
