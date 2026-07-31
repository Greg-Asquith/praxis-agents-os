# apps/api/integrations/gmail/tools/utils.py

"""Shared Gmail tool bindings, credential access, and per-entry audit."""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    IntegrationToolBinding,
    ToolFieldPresentation,
)
from services.audit_events import AuditStatus, record_integration_operation_audit_event
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
        await record_gmail_operation_audit(
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
        external_ref_from_result(result) if external_ref_from_result is not None else external_ref
    )
    await record_gmail_operation_audit(
        ctx,
        entry,
        tool_name=tool_name,
        operation=operation,
        status=AuditStatus.SUCCESS,
        external_ref=resolved_external_ref,
    )
    return result


async def record_gmail_operation_audit(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    status: AuditStatus,
    external_ref: str | None = None,
    error_code: str | None = None,
) -> None:
    """Record one Gmail resource attempt without provider content."""
    await record_integration_operation_audit_event(
        workspace_id=ctx.deps.workspace.id,
        agent=ctx.deps.agent,
        run=ctx.deps.run,
        tool_name=tool_name,
        provider_key="gmail",
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


def gmail_available() -> bool:
    return bool(gmail_settings.GMAIL_OAUTH_CLIENT_ID.strip())
