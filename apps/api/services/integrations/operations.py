# apps/api/services/integrations/operations.py

"""Provider-neutral audit orchestration for integration operations."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic_ai import RunContext

from core.exceptions.integration import IntegrationFailureDisposition
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    RuntimeToolDefinition,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationDetail,
    record_integration_operation_audit_event,
)
from services.integrations.context.domain import ResolvedContextEntry

type IntegrationTerminalAuditStatus = Literal[
    AuditStatus.SUCCESS,
    AuditStatus.FAILURE,
    AuditStatus.DENIED,
]
_TERMINAL_AUDIT_STATUSES = frozenset(
    {
        AuditStatus.SUCCESS,
        AuditStatus.FAILURE,
        AuditStatus.DENIED,
    }
)
_TERMINAL_AUDIT_FINALIZE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class IntegrationAuditOutcome[T]:
    value: T
    status: IntegrationTerminalAuditStatus = AuditStatus.SUCCESS
    external_ref: str | None = None
    operation_detail: IntegrationOperationDetail | None = None


async def run_audited_integration_operation[T](
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    execute: Callable[[], Awaitable[IntegrationAuditOutcome[T]]],
    pending_operation_detail: IntegrationOperationDetail | None = None,
) -> T:
    """Execute one provider operation with metadata-derived audit durability."""
    definition = _resolve_integration_definition(ctx, tool_name, entry)
    durable = _is_external_write(definition)
    if durable and pending_operation_detail is None:
        raise ValueError("External integration writes require pending operation detail")

    pending_event_id = None
    if durable:
        pending_event_id = await _record_operation(
            ctx,
            entry,
            tool_name=tool_name,
            operation=operation,
            status=AuditStatus.PENDING,
            operation_detail=pending_operation_detail,
            raise_on_error=True,
        )

    try:
        outcome = await execute()
        if outcome.status not in _TERMINAL_AUDIT_STATUSES:
            raise ValueError("Integration audit outcomes must have a terminal status")
    except asyncio.CancelledError as exc:
        disposition = getattr(
            exc,
            "failure_disposition",
            IntegrationFailureDisposition.NOT_DISPATCHED,
        )
        if durable:
            exc.failure_disposition = disposition
        with suppress(BaseException):
            await _record_terminal_operation(
                ctx,
                entry,
                tool_name=tool_name,
                operation=operation,
                status=AuditStatus.FAILURE,
                error_code=_failure_error_code(exc, disposition),
                operation_detail=pending_operation_detail,
                related_event_id=pending_event_id,
                raise_on_error=durable,
            )
        raise
    except Exception as exc:
        disposition = getattr(exc, "failure_disposition", None)
        if durable and disposition is None:
            disposition = IntegrationFailureDisposition.AMBIGUOUS
            exc.failure_disposition = disposition
        await _record_terminal_operation(
            ctx,
            entry,
            tool_name=tool_name,
            operation=operation,
            status=AuditStatus.FAILURE,
            error_code=_failure_error_code(exc, disposition),
            operation_detail=pending_operation_detail,
            related_event_id=pending_event_id,
            raise_on_error=durable,
        )
        raise

    await _record_terminal_operation(
        ctx,
        entry,
        tool_name=tool_name,
        operation=operation,
        status=outcome.status,
        external_ref=outcome.external_ref,
        operation_detail=outcome.operation_detail,
        related_event_id=pending_event_id,
        raise_on_error=durable,
    )
    return outcome.value


def _failure_error_code(
    exc: BaseException,
    disposition: IntegrationFailureDisposition | None,
) -> str:
    if disposition is IntegrationFailureDisposition.AMBIGUOUS:
        return "unverified_mutation"
    return exc.__class__.__name__


async def _record_terminal_operation(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    status: IntegrationTerminalAuditStatus,
    external_ref: str | None = None,
    error_code: str | None = None,
    operation_detail: IntegrationOperationDetail | None,
    related_event_id: UUID | None,
    raise_on_error: bool,
) -> None:
    async def record() -> None:
        try:
            async with asyncio.timeout(_TERMINAL_AUDIT_FINALIZE_TIMEOUT_SECONDS):
                await _record_operation(
                    ctx,
                    entry,
                    tool_name=tool_name,
                    operation=operation,
                    status=status,
                    external_ref=external_ref,
                    error_code=error_code,
                    operation_detail=operation_detail,
                    related_event_id=related_event_id,
                    raise_on_error=raise_on_error,
                )
        except TimeoutError:
            if raise_on_error:
                raise

    task = asyncio.create_task(record())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        with suppress(BaseException):
            await asyncio.shield(task)
        raise


async def record_integration_write_denial(
    ctx: RunContext[RuntimeDeps], entry: ResolvedContextEntry
) -> None:
    """Record generic denial evidence for a registered integration write."""
    definition = _resolve_dispatched_integration_definition(ctx)
    tool_name = definition.name
    _validate_definition_entry(definition, entry)
    if not _is_external_write(definition):
        raise RuntimeError("Write denial evidence requires an external-write tool")
    operation = tool_name.removeprefix(f"{entry.provider_key}_")
    await _record_operation(
        ctx,
        entry,
        tool_name=tool_name,
        operation=operation,
        status=AuditStatus.FAILURE,
        error_code="write_not_permitted",
    )


def _resolve_integration_definition(
    ctx: RunContext[RuntimeDeps],
    tool_name: str,
    entry: ResolvedContextEntry,
) -> RuntimeToolDefinition:
    definition = _resolve_dispatched_integration_definition(
        ctx,
        expected_tool_name=tool_name,
    )
    _validate_definition_entry(definition, entry)
    return definition


def _resolve_dispatched_integration_definition(
    ctx: RunContext[RuntimeDeps],
    *,
    expected_tool_name: str | None = None,
) -> RuntimeToolDefinition:
    from services.agents.runtime.tools.registry import get_runtime_tool_definition

    tool_name = (getattr(ctx, "tool_name", None) or "").strip()
    if expected_tool_name is not None and tool_name != expected_tool_name:
        raise RuntimeError("Integration operation tool name does not match the dispatched tool")
    definition = get_runtime_tool_definition(tool_name)
    if definition is None:
        raise RuntimeError(f"Unknown integration runtime tool: {tool_name or '<missing>'}")
    if definition.integration_binding is None:
        raise RuntimeError("Dispatched runtime tool is not bound to an integration resource")
    return definition


def _validate_definition_entry(
    definition: RuntimeToolDefinition,
    entry: ResolvedContextEntry,
) -> None:
    binding = definition.integration_binding
    if binding is None:  # Guarded by _resolve_dispatched_integration_definition.
        raise RuntimeError("Dispatched runtime tool is not bound to an integration resource")
    if (
        definition.provider != entry.provider_key
        or entry.provider_key not in binding.provider_keys
        or entry.resource_type not in binding.resource_types
    ):
        raise RuntimeError("Integration operation does not match its registered provider binding")


def _is_external_write(definition: RuntimeToolDefinition) -> bool:
    return (
        definition.effect == TOOL_EFFECT_WRITE and definition.egress == TOOL_EGRESS_EXTERNAL_WRITE
    )


async def _record_operation(
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
        provider_key=entry.provider_key,
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
