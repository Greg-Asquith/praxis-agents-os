# apps/api/integrations/meta_ads/tools/update_budgets.py

"""Approval-only tool that changes Meta campaign and ad set budget amounts."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import resolve_runtime_references
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..models import MetaAdsObjectBudget
from ..money import amount_to_minor
from ..operations.get_account import get_account
from ..operations.mutations import MetaAdsMutationLedger
from ..operations.update_budgets import (
    MetaAdsBudgetObjectType,
    MetaAdsBudgetTarget,
    MetaAdsRecentBudgetChanges,
    budget_problem,
    budget_target,
    count_recent_budget_changes,
    lifetime_spent,
    read_budget_objects,
    update_budgets,
    validate_budget,
    validate_budgets,
)
from ..operations.values import require_currency
from ..references import MetaAdsAdSetReference, MetaAdsCampaignReference
from ..throttle import ensure_account_available
from .schemas.budgets import MetaAdsBudgetOutput, MetaAdsBudgetUpdate
from .utils.bindings import META_ADS_BINDING, META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client, meta_ads_client_for_principal
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)

_OPERATION = "update_budgets"
_MAX_UPDATES = 50
_REFERENCE_KEYS: tuple[tuple[str, str, MetaAdsBudgetObjectType], ...] = (
    ("campaign", "meta_ads_campaign", "campaign"),
    ("ad_set", "meta_ads_ad_set", "adset"),
)
_GROUP_KEYS = {"campaign": "campaigns", "adset": "ad-sets"}
_ENTITY_TYPES = {"campaign": "meta_ads_campaign", "adset": "meta_ads_ad_set"}

type _Reference = MetaAdsCampaignReference | MetaAdsAdSetReference
type _Key = tuple[str, MetaAdsBudgetObjectType, str]


async def meta_ads_update_budgets(
    ctx: RunContext[RuntimeDeps],
    updates: Annotated[
        list[MetaAdsBudgetUpdate],
        Field(min_length=1, max_length=_MAX_UPDATES, description="Budget amount changes."),
    ],
) -> dict[str, Any]:
    requested = _requested_amounts(updates)

    async def operation(entry: ResolvedContextEntry, selected: Sequence[_Reference]) -> Any:
        client: MetaAdsClient | None = None
        targets: list[MetaAdsBudgetTarget] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, targets, pending_detail
            ensure_account_available(entry.external_id, operation=_OPERATION)
            client = await meta_ads_client(ctx, entry)
            targets = await _live_targets(client, entry, selected, requested)
            pending_detail = _pending_operation_detail(entry, targets)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending_detail is None or not targets:
                raise RuntimeError("Meta Ads budget change preparation did not complete")
            try:
                ledger = await update_budgets(
                    client, account_id=entry.external_id, currency=_currency(entry), targets=targets
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending_detail, identity_key="object_id")
                raise
            detail = terminal_operation_detail(pending_detail, ledger, identity_key="object_id")
            result = _result(entry.external_id, _currency(entry), targets, ledger)
            outcome_status = audit_status(detail)
            return IntegrationAuditOutcome(
                result,
                status=outcome_status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=result if outcome_status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_update_budgets",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=META_ADS_WRITE_BINDING,
        references=[update.reference for update in updates],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _requested_amounts(updates: Sequence[MetaAdsBudgetUpdate]) -> dict[_Key, Decimal]:
    if not updates:
        raise ModelRetry("Choose at least one Meta Ads campaign or ad set budget.")
    if len(updates) > _MAX_UPDATES:
        raise ModelRetry(f"Choose at most {_MAX_UPDATES} Meta Ads budgets per change.")
    requested: dict[_Key, Decimal] = {}
    for update in updates:
        key = _key(update.reference)
        if key in requested:
            raise ModelRetry("Choose each Meta Ads campaign or ad set only once.")
        requested[key] = Decimal(update.amount)
    return requested


def _key(reference: _Reference) -> _Key:
    return reference.account_id, _object_type(reference), reference.provider_entity_id


def _object_type(reference: _Reference) -> MetaAdsBudgetObjectType:
    return "campaign" if isinstance(reference, MetaAdsCampaignReference) else "adset"


def _minor(amount: Decimal, currency: str) -> int | None:
    try:
        return amount_to_minor(amount, currency)
    except ValueError:
        return None


def _precision_problem(currency: str) -> str:
    return f"Use whole {currency} amounts for Meta Ads budgets."


def _currency(entry: ResolvedContextEntry) -> str:
    return require_currency(
        metadata_str(entry.permissions_metadata.get("currency")), operation=_OPERATION
    )


async def _live_targets(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    selected: Sequence[_Reference],
    requested: Mapping[_Key, Decimal],
) -> list[MetaAdsBudgetTarget]:
    """Re-reads each budget, applies the routing and amount rules, then asks Meta to check it."""
    currency = _currency(entry)
    object_ids: dict[MetaAdsBudgetObjectType, list[str]] = defaultdict(list)
    for reference in selected:
        object_ids[_object_type(reference)].append(reference.provider_entity_id)
    objects = await read_budget_objects(
        client, account_id=entry.external_id, currency=currency, object_ids=object_ids
    )
    minimum = (await get_account(client, account_id=entry.external_id)).min_daily_budget
    targets: list[MetaAdsBudgetTarget] = []
    for reference in selected:
        object_type = _object_type(reference)
        item = objects[object_type].get(reference.provider_entity_id)
        if item is None:
            raise ModelRetry(
                "Some selected Meta Ads budgets are no longer in this ad account. Choose them again."
            )
        amount = requested[_key(reference)]
        minor = _minor(amount, currency)
        if minor is None:
            raise ModelRetry(_precision_problem(currency))
        problem = budget_problem(
            object_type,
            item.status,
            item.budget,
            amount,
            currency=currency,
            min_daily_budget=minimum,
        )
        if problem:
            raise ModelRetry(f"{item.name or item.id}: {problem}")
        targets.append(budget_target(object_type, item, amount, minor))
    rejected = await validate_budgets(client, account_id=entry.external_id, targets=targets)
    if rejected:
        names = {target.object_id: target.before.name or target.object_id for target in targets}
        reasons = " ".join(
            f"{names[object_id]}: {reason}" for object_id, reason in rejected.items()
        )
        raise ModelRetry(f"Meta Ads rejected these budgets, so nothing was changed. {reasons}")
    return targets


def _pending_operation_detail(
    entry: ResolvedContextEntry, targets: Sequence[MetaAdsBudgetTarget]
) -> PendingIntegrationOperationDetail:
    currency = _currency(entry)
    groups: dict[MetaAdsBudgetObjectType, list[IntegrationOperationIntent]] = defaultdict(list)
    for target in targets:
        fields = {
            "object_id": target.object_id,
            "object_name": target.before.name,
            "budget_kind": target.kind,
            "previous_amount": target.previous_amount,
            "requested_amount": target.requested_amount,
            "currency": currency,
        }
        groups[target.object_type].append(
            IntegrationOperationIntent(
                fields={key: value for key, value in fields.items() if value is not None}
            )
        )
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{_GROUP_KEYS[object_type]}:update-budget",
                action="update_budget",
                entity_type=_ENTITY_TYPES[object_type],
                items=items,
            )
            for object_type, items in groups.items()
        ],
    )


def _result(
    account_id: str,
    currency: str,
    targets: Sequence[MetaAdsBudgetTarget],
    ledger: MetaAdsMutationLedger,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object_id"]: parent for parent in ledger.parents}
    budgets = []
    for target in targets:
        parent = parents[target.object_id]
        effect = parent.effects[0] if parent.effects else None
        if parent.decision == "skipped":
            amount = target.previous_amount
        else:
            amount = dict(effect.fields).get("amount") if effect is not None else None
        budgets.append(
            {
                "object_type": target.object_type,
                "object_id": target.object_id,
                "object_name": target.before.name,
                "budget_kind": target.kind,
                "previous_amount": target.previous_amount,
                "requested_amount": target.requested_amount,
                "amount": amount,
                "outcome": {"applied": "updated", "skipped": "already_set"}.get(
                    parent.outcome, parent.outcome
                ),
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": account_id, "currency": currency, "budgets": budgets}


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates live budgets and adds, per object, what blocks or warns about the change."""
    updates = args.get("updates")
    if not isinstance(updates, list) or not updates:
        raise TypeError("Meta Ads budget approval arguments are invalid")
    display_updates = [dict(update) for update in updates if isinstance(update, Mapping)]
    if len(display_updates) != len(updates):
        raise TypeError("Meta Ads budget approval arguments are invalid")
    for key, entity_kind, _object_type in _REFERENCE_KEYS:
        positions = [index for index, update in enumerate(display_updates) if update.get(key)]
        if not positions:
            continue
        hydrated = await resolve_runtime_references(
            deps,
            entity_kind=entity_kind,
            field_key="updates",
            values=[dict(display_updates[index][key]) for index in positions],
        )
        for index, reference in zip(positions, hydrated, strict=True):
            display_updates[index][key] = reference
    return {
        **args,
        "updates": display_updates,
        "_budget_checks": await _budget_checks(deps, display_updates),
    }


async def _budget_checks(
    deps: RuntimeDeps, updates: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Returns, per object ID, the rule the change breaks, the spent amount, and recent changes.

    Objects that can't be read or checked with Meta are marked unavailable, so the card says so.
    """
    by_account: dict[str, list[tuple[MetaAdsBudgetObjectType, Mapping[str, Any], str]]] = (
        defaultdict(list)
    )
    for update in updates:
        for key, _entity_kind, object_type in _REFERENCE_KEYS:
            if isinstance(reference := update.get(key), Mapping):
                by_account[str(reference["account_id"])].append(
                    (object_type, reference, str(update.get("amount")))
                )
    active_context = deps.active_context
    entries = {
        entry.external_id: entry
        for entry in (active_context.compatible_entries(META_ADS_BINDING) if active_context else ())
    }
    checks: dict[str, dict[str, Any]] = {}
    for account_id, items in by_account.items():
        entry = entries.get(account_id)
        try:
            if entry is None:
                raise LookupError(account_id)
            client = await meta_ads_client_for_principal(
                deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
            )
            checks.update(await _account_checks(client, entry, items))
        except (IntegrationError, LookupError):
            checks.update(
                {
                    _reference_id(object_type, item): {"unavailable": True}
                    for object_type, item, _ in items
                }
            )
    return checks


async def _account_checks(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    items: Sequence[tuple[MetaAdsBudgetObjectType, Mapping[str, Any], str]],
) -> dict[str, dict[str, Any]]:
    minimum = (await get_account(client, account_id=entry.external_id)).min_daily_budget
    recent = await _recent_changes(
        client, entry, [_reference_id(object_type, item) for object_type, item, _ in items]
    )
    checks: dict[str, dict[str, Any]] = {}
    for object_type, reference, amount in items:
        object_id = _reference_id(object_type, reference)
        budget = _budget(reference.get("budget"))
        spent = lifetime_spent(budget) if budget is not None else None
        problem, unavailable = await _change_problem(
            client, entry, object_type, reference, budget, Decimal(amount), minimum
        )
        checks[object_id] = {
            "problem": problem,
            "unavailable": unavailable,
            "min_daily_budget": minimum,
            "spent": format(spent, "f") if spent is not None else None,
            "recent_changes": recent.counts.get(object_id) if recent is not None else None,
            "recent_changes_complete": recent is not None and recent.complete,
        }
    return checks


async def _recent_changes(
    client: MetaAdsClient, entry: ResolvedContextEntry, object_ids: Sequence[str]
) -> MetaAdsRecentBudgetChanges | None:
    try:
        return await count_recent_budget_changes(
            client,
            account_id=entry.external_id,
            timezone_name=metadata_str(entry.permissions_metadata.get("timezone_name")) or "UTC",
            object_ids=object_ids,
            now=datetime.now(UTC),
        )
    except IntegrationError:
        # The warning is advisory, so an unreadable history doesn't hide the rest of the checks.
        return None


async def _change_problem(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    object_type: MetaAdsBudgetObjectType,
    reference: Mapping[str, Any],
    budget: MetaAdsObjectBudget | None,
    amount: Decimal,
    minimum: str | None,
) -> tuple[str | None, bool]:
    """Returns why the change can't be made, and whether Meta couldn't check it."""
    currency = _currency(entry)
    minor = _minor(amount, currency)
    if minor is None:
        return _precision_problem(currency), False
    problem = budget_problem(
        object_type,
        reference.get("status"),
        budget,
        amount,
        currency=currency,
        min_daily_budget=minimum,
    )
    if problem is not None or budget is None or budget.kind == "campaign":
        return problem, False
    if budget.amount is not None and Decimal(budget.amount) == amount:
        return None, False
    try:
        reason = await validate_budget(
            client,
            account_id=entry.external_id,
            object_id=_reference_id(object_type, reference),
            kind=budget.kind,
            requested_minor=minor,
        )
    except IntegrationError:
        # Execution checks again with Meta, so an unchecked change stays approvable.
        return None, True
    return reason, False


def _reference_id(object_type: MetaAdsBudgetObjectType, reference: Mapping[str, Any]) -> str:
    return str(reference["campaign_id" if object_type == "campaign" else "adset_id"])


def _budget(value: Any) -> MetaAdsObjectBudget | None:
    try:
        return MetaAdsObjectBudget.model_validate(value) if value is not None else None
    except ValidationError:
        return None


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_update_budgets",
    function=meta_ads_update_budgets,
    description=(
        "Set operator-chosen daily or lifetime budget amounts on named Meta campaigns or ad "
        "sets, up to 50 per call. Each update names one campaign or one ad set. Change a "
        "campaign when the campaign holds the budget, otherwise change each ad set. The amount "
        "replaces the budget the object already has, and doesn't switch daily and lifetime. "
        "Meta checks every change before any is made. Each result reports the amount Meta "
        "shows after the change. This tool doesn't recommend or choose an amount."
    ),
    provider="meta_ads",
    label="Update Meta Ads Budgets",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=MetaAdsBudgetOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Updating Meta Ads Budgets",
        completed_label="Updated Meta Ads Budgets",
        failed_label="Couldn't Update Meta Ads Budgets",
        approval_title="Change Meta Ads Budgets",
        approval_prompt="The agent wants to change these Meta Ads budgets.",
        approve_label="Approve & Update",
        arg_fields=(ToolFieldPresentation(key="updates", label="Budget Changes"),),
        result_fields=RESULTS_FIELD,
    ),
)
