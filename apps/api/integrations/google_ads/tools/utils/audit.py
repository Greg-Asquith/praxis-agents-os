# apps/api/integrations/google_ads/tools/utils/audit.py

"""Google Ads runtime-tool audit helpers."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.audit_events import (
    AuditStatus,
    IntegrationOperationDetail,
    record_integration_operation_audit_event,
)
from services.integrations.context.domain import ResolvedContextEntry


async def run_audited_operation(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    execute: Callable[[], Awaitable[Any]],
    external_ref_from_result: Callable[[Any], str | None] | None = None,
    operation_detail_from_result: Callable[[Any], IntegrationOperationDetail] | None = None,
    status_from_result: Callable[[Any], AuditStatus] | None = None,
    pending_operation_detail: IntegrationOperationDetail | None = None,
    require_durable_audit: bool = False,
) -> Any:
    pending_event_id = None
    if pending_operation_detail is not None:
        pending_event_id = await record_google_ads_operation_audit(
            ctx,
            entry,
            tool_name=tool_name,
            operation=operation,
            status=AuditStatus.PENDING,
            operation_detail=pending_operation_detail,
            raise_on_error=require_durable_audit,
        )
    try:
        result = await execute()
    except Exception as exc:
        await record_google_ads_operation_audit(
            ctx,
            entry,
            tool_name=tool_name,
            operation=operation,
            status=AuditStatus.FAILURE,
            error_code=exc.__class__.__name__,
            operation_detail=pending_operation_detail,
            related_event_id=pending_event_id,
        )
        raise
    external_ref = external_ref_from_result(result) if external_ref_from_result else None
    operation_detail = (
        operation_detail_from_result(result) if operation_detail_from_result else None
    )
    status = status_from_result(result) if status_from_result else AuditStatus.SUCCESS
    await record_google_ads_operation_audit(
        ctx,
        entry,
        tool_name=tool_name,
        operation=operation,
        status=status,
        external_ref=external_ref,
        operation_detail=operation_detail,
        related_event_id=pending_event_id,
        raise_on_error=require_durable_audit,
    )
    return result


async def record_google_ads_operation_audit(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    status: AuditStatus,
    external_ref: str | None = None,
    error_code: str | None = None,
    operation_detail: IntegrationOperationDetail | None = None,
    related_event_id: UUID | None = None,
    raise_on_error: bool = False,
) -> UUID | None:
    return await record_integration_operation_audit_event(
        workspace_id=ctx.deps.workspace.id,
        agent=ctx.deps.agent,
        run=ctx.deps.run,
        tool_call_id=getattr(ctx, "tool_call_id", None),
        tool_name=tool_name,
        provider_key="google_ads",
        connection_id=entry.connection_id,
        integration_resource_id=entry.integration_resource_id,
        external_id=entry.external_id,
        operation=operation,
        status=status,
        external_ref=external_ref,
        error_code=error_code,
        operation_detail=operation_detail,
        related_event_id=related_event_id,
        raise_on_error=raise_on_error,
    )
