# apps/api/integrations/meta_ads/tools/utils/create_operation.py

"""Shared flow for approval-only Meta Ads tools that create objects in one ad account."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.audit_events import AuditStatus, PendingIntegrationOperationDetail
from services.integrations.approved_display_args import approved_display_args, proposed_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ...client import MetaAdsClient
from ...operations.list_objects import list_objects
from ...operations.mutations import MetaAdsMutationLedger
from ...throttle import ensure_account_available
from ..schemas.objects import OBJECT_STATUSES, MetaAdsObjectType
from .bindings import META_ADS_WRITE_BINDING
from .client import meta_ads_client
from .mutation_evidence import (
    account_pin,
    attach_interrupted_evidence,
    audit_status,
    terminal_operation_detail,
)
from .validation import validation_retry

ACCOUNT_CHANGED = "The approved ad account is no longer selected. Ask for approval again."


async def ensure_name_free(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    *,
    object_type: MetaAdsObjectType,
    name: str,
    currency: str,
    taken: str,
    campaign_ids: list[str] | None = None,
) -> None:
    """A lost reply is found by name, so the name must be free among undeleted objects."""
    existing = await list_objects(
        client,
        account_id=entry.external_id,
        object_type=object_type,
        statuses=[status for status in OBJECT_STATUSES[object_type] if status != "DELETED"],
        campaign_ids=campaign_ids,
        name_contains=name,
        limit=50,
        currency=currency,
    )
    if any(item.name == name for item in existing.objects):
        raise ModelRetry(f"{taken} Choose another name.")


class _Run(Protocol):
    def ledger(self) -> MetaAdsMutationLedger: ...


def given(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def validated[M: BaseModel](model: type[M], values: Mapping[str, Any]) -> M:
    """Validates the whole request, naming the first invalid argument for the model to fix."""
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise validation_retry(exc) from None


def selected_account(deps: RuntimeDeps, account_id: str, message: str) -> ResolvedContextEntry:
    """Finds the one writable-bound ad account in Active Context with this ID."""
    active = deps.active_context
    entries = active.compatible_entries(META_ADS_WRITE_BINDING) if active else ()
    matching = [entry for entry in entries if entry.external_id == account_id]
    if len(matching) != 1:
        raise ModelRetry(message)
    return matching[0]


async def run_create_tool[P, R: _Run](
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    prepare: Callable[[MetaAdsClient, ResolvedContextEntry], Awaitable[P]],
    pending_detail: Callable[[ResolvedContextEntry, P], PendingIntegrationOperationDetail],
    run: Callable[[MetaAdsClient, ResolvedContextEntry, P], Awaitable[R]],
    result: Callable[[R, ResolvedContextEntry, P], dict[str, Any]],
    check_edits: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Pins the approved account, refuses edits `check_edits` rejects, dry-runs, runs, and audits."""
    reviewed = approved_display_args(ctx)

    async def scoped(selected: ResolvedContextEntry) -> Any:
        client: MetaAdsClient | None = None
        prepared: P | None = None
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, prepared, pending
            if reviewed.get("_account") != account_pin(selected):
                raise ModelRetry(ACCOUNT_CHANGED)
            if check_edits is not None:
                check_edits(proposed_args(ctx))
            ensure_account_available(selected.external_id, operation=operation)
            client = await meta_ads_client(ctx, selected)
            prepared = await prepare(client, selected)
            pending = pending_detail(selected, prepared)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or prepared is None or pending is None:
                raise RuntimeError(f"{tool_name} preparation did not complete")
            try:
                finished = await run(client, selected, prepared)
            except (asyncio.CancelledError, Exception) as exc:
                attach_interrupted_evidence(
                    exc, pending, identity_key="key", refs_mean_changed=True
                )
                raise
            ledger = finished.ledger()
            detail = terminal_operation_detail(pending, ledger, identity_key="key")
            output = result(finished, selected, prepared)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                output,
                status=status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=output if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            selected,
            tool_name=tool_name,
            operation=operation,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_scope(
        ctx,
        binding=META_ADS_WRITE_BINDING,
        provider_scope_id=entry.external_id,
        operation=scoped,
    )
    return {"results": serialize_fan_out_results(results)}
