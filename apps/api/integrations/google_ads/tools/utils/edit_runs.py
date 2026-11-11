# apps/api/integrations/google_ads/tools/utils/edit_runs.py

"""Runs one account's approved edits as one audited Google Ads operation."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.audit_events import AuditStatus, PendingIntegrationOperationDetail
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ...client import GoogleAdsClient
from ...operations.edits import Edit, EditResult, ReadState, apply_edits
from .client import google_ads_client
from .mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    terminal_operation_detail,
)
from .routing import login_customer_id

# Every edit's audit intent and ledger entry are matched on the object the edit changes.
EDIT_IDENTITY = ("object",)

type EditPlan = tuple[Sequence[Edit], PendingIntegrationOperationDetail]


async def run_approved_edits(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    family: str,
    plan: Callable[[GoogleAdsClient], Awaitable[EditPlan]],
    read: Callable[[GoogleAdsClient], ReadState],
    result: Callable[[GoogleAdsClient, EditResult], Awaitable[dict[str, Any]]],
) -> Any:
    """Applies the edits `plan` builds for one account and audits what Google Ads did.

    `plan` returns the edits with one audit intent per edit, keyed by `object`. `read`
    returns the live values `apply_edits` checks and reads back. `result` builds the tool
    result for the account. A run cancelled after the edits are sent keeps their outcomes
    in the audit record.
    """
    client: GoogleAdsClient | None = None
    edits: Sequence[Edit] = ()
    pending: PendingIntegrationOperationDetail | None = None

    async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
        nonlocal client, edits, pending
        client = await google_ads_client(ctx, entry)
        edits, pending = await plan(client)
        return pending

    async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
        if client is None or pending is None or not edits:
            raise RuntimeError(f"Google Ads {operation} preparation did not complete")
        try:
            applied = await apply_edits(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                edits=edits,
                read=read(client),
                family=family,
                operation=operation,
            )
        except asyncio.CancelledError as exc:
            attach_interrupted_evidence(exc, pending, identity_keys=EDIT_IDENTITY)
            raise
        try:
            data = await result(client, applied)
        except asyncio.CancelledError as exc:
            # The edits are already applied, so the audit record keeps their outcomes.
            exc.ledger = applied.ledger  # type: ignore[attr-defined]
            attach_interrupted_evidence(exc, pending, identity_keys=EDIT_IDENTITY)
            raise
        detail = terminal_operation_detail(pending, applied.ledger, identity_keys=EDIT_IDENTITY)
        status = audit_status(detail)
        return IntegrationAuditOutcome(
            data,
            status=status,
            external_ref=",".join(applied.ledger.external_refs)[:1000] or None,
            operation_detail=detail,
            unverified_result=data if status is AuditStatus.UNVERIFIED else None,
        )

    return await run_audited_integration_operation(
        ctx,
        entry,
        tool_name=tool_name,
        operation=operation,
        execute=execute,
        prepare_pending_operation=prepare_pending_operation,
    )
