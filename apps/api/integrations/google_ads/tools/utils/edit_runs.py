# apps/api/integrations/google_ads/tools/utils/edit_runs.py

"""Runs one account's approved edits, and the build that follows them, as one audited operation."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
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
from ...operations.build import CampaignBuild, send_build
from ...operations.edits import Edit, EditResult, ReadState, apply_edits
from ...operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
    joined_ledger,
)
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

_INTERRUPTED = "This wasn't sent, because the change was interrupted."


@dataclass(frozen=True, slots=True)
class EditBuildPlan:
    """One account's approved edits, and the new objects to build after them."""

    edits: Sequence[Edit]
    # Each step's `source` is the audit object of the change it came from.
    build: CampaignBuild
    # Why each part left out of the build isn't sent, by audit object.
    refused: Mapping[str, str]
    # One audit intent per edit, build step, and refused part, keyed by `object`.
    pending: PendingIntegrationOperationDetail


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


async def run_approved_edits_then_build(
    ctx: RunContext[RuntimeDeps],
    entry: ResolvedContextEntry,
    *,
    tool_name: str,
    operation: str,
    family: str,
    plan: Callable[[], EditBuildPlan],
    read: Callable[[GoogleAdsClient], ReadState],
    result: Callable[[GoogleAdsMutationLedger], dict[str, Any]],
) -> Any:
    """Applies one account's edits, then creates its new objects in one atomic request.

    The edits go first, so a removal frees room before the build adds to the same object.
    `result` builds the tool result from the one ledger that records both. A run cancelled
    part way keeps every outcome Google already gave in the audit record.
    """
    client: GoogleAdsClient | None = None
    planned: EditBuildPlan | None = None

    async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
        nonlocal client, planned
        client = await google_ads_client(ctx, entry)
        planned = plan()
        return planned.pending

    async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
        if client is None or planned is None:
            raise RuntimeError(f"Google Ads {operation} preparation did not complete")
        try:
            ledger = await _send_edits_then_build(
                client, entry, planned, read=read(client), family=family, operation=operation
            )
        except asyncio.CancelledError as exc:
            attach_interrupted_evidence(exc, planned.pending, identity_keys=EDIT_IDENTITY)
            raise
        detail = terminal_operation_detail(planned.pending, ledger, identity_keys=EDIT_IDENTITY)
        data = result(ledger)
        status = audit_status(detail)
        return IntegrationAuditOutcome(
            data,
            status=status,
            external_ref=",".join(ledger.external_refs)[:1000] or None,
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


async def _send_edits_then_build(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    plan: EditBuildPlan,
    *,
    read: ReadState,
    family: str,
    operation: str,
) -> GoogleAdsMutationLedger:
    keys = [step.source for step in plan.build.steps]
    ledgers: list[GoogleAdsMutationLedger] = []
    if plan.edits:
        try:
            applied = await apply_edits(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                edits=plan.edits,
                read=read,
                family=family,
                operation=operation,
            )
        except asyncio.CancelledError as exc:
            # A change interrupted before anything was sent carries no ledger.
            sent = getattr(exc, "ledger", None)
            unsent = dict.fromkeys([*keys, *plan.refused], _INTERRUPTED)
            if sent is not None and unsent:
                exc.ledger = joined_ledger(
                    [sent, _unsent_ledger(family, unsent, "CANCELLED")], family=family
                )
            raise
        ledgers.append(applied.ledger)
    refused = [_unsent_ledger(family, plan.refused, "REFUSED")] if plan.refused else []
    if keys:
        try:
            built = await send_build(
                client,
                plan.build,
                login_customer_id=login_customer_id(entry),
                family=family,
                operation=operation,
            )
        except asyncio.CancelledError as exc:
            exc.ledger = joined_ledger(
                [*ledgers, _keyed(exc.ledger, keys), *refused], family=family
            )
            raise
        ledgers.append(_keyed(built.ledger, keys))
    return joined_ledger([*ledgers, *refused], family=family)


def _keyed(ledger: GoogleAdsMutationLedger, keys: Sequence[str]) -> GoogleAdsMutationLedger:
    """Names each build step by its change's key, as the audit record names every change."""
    parents = []
    for parent, key in zip(ledger.parents, keys, strict=True):
        identity = freeze_fields({"object": key, "settings": "create"})
        effects = tuple(replace(effect, fields=identity) for effect in parent.effects)
        parents.append(replace(parent, identity=identity, effects=effects))
    return replace(ledger, parents=tuple(parents))


def _unsent_ledger(family: str, reasons: Mapping[str, str], code: str) -> GoogleAdsMutationLedger:
    """Records build parts that weren't sent as failed, each with its reason."""
    fields = [{"object": key, "settings": "create"} for key in reasons]
    return build_mutation_ledger(
        family=family,
        action="update",
        parent_fields=fields,
        skipped_indices={},
        submitted=list(enumerate(fields)),
        outcomes=[("failed", None, code, reason) for reason in reasons.values()],
        projection=GoogleAdsMutationProjection(
            applied_key="updated", skipped_key="already_set", errors_key="errors"
        ),
    )
