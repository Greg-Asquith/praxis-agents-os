# apps/api/integrations/google_ads/tools/update_budgets.py

"""Approval-only tool that changes daily budgets and moves campaigns onto shared budgets."""

import calendar
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

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
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets

from ..client import GoogleAdsClient
from ..operations.budget_settings import (
    AMOUNT_PATH,
    CAMPAIGN_BUDGET_PATH,
    DELIVERY_PATH,
    NETWORK_PATH,
    REFERENCE_COUNT_PATH,
    BudgetCampaign,
    LiveBudget,
    LiveCampaign,
    network_code,
    network_setting_for,
    read_budget_campaigns,
    read_budgets,
    read_campaigns,
    with_network_setting,
)
from ..operations.campaign_bidding import money
from ..operations.edits import (
    Edit,
    EditResult,
    FieldChange,
    Removal,
    SettingValues,
    prepare_edits,
)
from .schemas.budget_updates import (
    MAX_BUDGET_UPDATES,
    BudgetSetting,
    GoogleAdsBudgetUpdate,
    GoogleAdsNetworkPriority,
    GoogleAdsUpdateBudgetsOutput,
    GoogleAdsUpdateBudgetsRequest,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entries
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client_for_principal
from .utils.edit_runs import EditPlan, run_approved_edits
from .utils.money import money_to_micros
from .utils.mutation_evidence import (
    google_ads_account_target,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_budgets"
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}
# The card names this many of the campaigns a shared budget funds; the count covers the rest.
_LISTED_CAMPAIGNS = 50

_MISSING = "{name} no longer exists in Google Ads."
_REMOVED = "{name} has been removed, so its budget can't change."
_TOTAL = "{name} is a total for the campaign's run, not a daily budget, so it can't change here."
_NOT_SHARED = "{name} isn't a shared budget, so only its own campaign can use it."
_EXPERIMENT = "Draft and experiment campaigns keep the budget of the campaign they test."
_TWICE = "Another change in this request already changes {name}. Cancel one of them."
_NO_CAMPAIGNS = "No campaign uses {name}, so there are no networks to put in order."
_MIXED_TYPES = "{name} funds campaigns of different types, so its networks can't be put in order."
_INELIGIBLE = "Google can't put the networks of {name} in order, because {reasons}."
_ALL_NETWORKS = " Put every network these campaigns can show on under First or After."
# Google's reasons a budget can't take a network order, in the card's words.
_INELIGIBLE_REASONS = {
    "HAS_ENABLED_TRIALS": "a campaign on it has an experiment running",
    "INSUFFICIENT_ELIGIBLE_CHANNELS": "its campaigns show on one network only",
    "MIXED_BIDDING_STRATEGIES": "its campaigns use different bidding strategies",
    "MIXED_CAMPAIGN_TYPES": "its campaigns are of different types",
    "UNSUPPORTED_BIDDING_STRATEGY": "its campaigns' bidding strategy doesn't allow it",
}


@dataclass(frozen=True, slots=True)
class _Plan:
    """What one change does in Google Ads, worked out from live state."""

    # The budget whose amount or delivery changes, or the campaign's budget before a move.
    budget: LiveBudget | None
    destination: LiveBudget | None
    edits: list[Edit]
    problem: str | None
    # The campaign's own budget is removed once nothing uses it.
    removes_budget: bool = False
    # The budget's network settings once the change is made; None follows the account.
    network: Sequence[Mapping[str, Any]] | None = None
    # The campaign type the network order is for, as Google names it.
    channel_type: str | None = None


def _budget_edits(
    change: GoogleAdsBudgetUpdate, budget: str, network: Sequence[Mapping[str, Any]] | None
) -> FieldChange:
    requested: dict[str, Any] = {}
    if change.amount is not None:
        requested[AMOUNT_PATH] = str(money_to_micros(change.amount))
    if change.delivery is not None:
        requested[DELIVERY_PATH] = change.delivery
    if change.network_priority is not None:
        requested[NETWORK_PATH] = network
    # A campaign that joined or left the budget since approval makes the change stale.
    return FieldChange(
        resource="campaignBudget",
        resource_name=budget,
        requested=requested,
        compared=(REFERENCE_COUNT_PATH,),
    )


def _edits(
    change: GoogleAdsBudgetUpdate,
    budget: str | None,
    *,
    removes: bool,
    network: Sequence[Mapping[str, Any]] | None = None,
) -> list[Edit]:
    """The edits for one change; a move and the removal of the budget it frees succeed together."""
    if change.shared_budget_name is None:
        return [_budget_edits(change, budget or change.resource_name, network)]
    group = change.resource_name if removes and budget else None
    move = FieldChange(
        resource="campaign",
        resource_name=change.resource_name,
        requested={CAMPAIGN_BUDGET_PATH: change.shared_budget_name},
        atomic_group=group,
    )
    if group is None or budget is None:
        return [move]
    return [move, Removal(resource="campaignBudget", resource_name=budget, atomic_group=group)]


def _refused(change: GoogleAdsBudgetUpdate, reason: str) -> list[Edit]:
    """One never-sent edit keyed by the change itself, so it can't collide with another change."""
    edit = _edits(change, None, removes=False)[0]
    resource = "campaign" if change.campaign is not None else "campaignBudget"
    return [replace(edit, resource=resource, resource_name=change.resource_name, refused=reason)]


def _budget_problem(budget: LiveBudget | None, label: str) -> str | None:
    if budget is None:
        return _MISSING.format(name=label)
    if budget.status == "REMOVED":
        return _REMOVED.format(name=budget.name)
    return _TOTAL.format(name=budget.name) if budget.period != "DAILY" else None


def _network_plan(
    change: GoogleAdsBudgetUpdate, budget: LiveBudget, funded: Sequence[BudgetCampaign]
) -> tuple[Sequence[Mapping[str, Any]] | None, str | None, str | None]:
    """The budget's network settings after the change, their campaign type, and any problem.

    A budget's campaigns say which campaign type the order is for. Taking the order off needs
    no eligible budget; with no single campaign type it takes every type's order off.
    """
    types = {item.channel_type for item in funded if item.budget == budget.resource_name}
    channel_type = next(iter(types)) if len(types) == 1 else None
    live = budget.values.get(NETWORK_PATH)
    priority = change.network_priority
    if not isinstance(priority, GoogleAdsNetworkPriority):
        return with_network_setting(live, channel_type, None), channel_type, None
    if budget.network_ineligible:
        reasons = [
            _INELIGIBLE_REASONS.get(reason, reason.replace("_", " ").lower())
            for reason in budget.network_ineligible
        ]
        problem = _INELIGIBLE.format(name=budget.name, reasons=" and ".join(reasons))
        return None, channel_type, problem
    if channel_type is None:
        problem = (_MIXED_TYPES if types else _NO_CAMPAIGNS).format(name=budget.name)
        return None, None, problem
    setting = priority.setting(channel_type)
    return with_network_setting(live, channel_type, setting), channel_type, None


def _plan(
    change: GoogleAdsBudgetUpdate,
    campaigns: Mapping[str, LiveCampaign],
    budgets: Mapping[str, LiveBudget],
    named_budgets: frozenset[str],
    funded: Sequence[BudgetCampaign],
) -> _Plan:
    """Finds the budget a change acts on and why it can't be made, if it can't."""
    campaign = campaigns.get(change.resource_name) if change.campaign is not None else None
    if change.campaign is not None and (campaign is None or campaign.status == "REMOVED"):
        problem = (_MISSING if campaign is None else _REMOVED).format(name=change.label)
        return _Plan(None, None, _refused(change, problem), problem)
    budget = budgets.get(campaign.budget if campaign else change.resource_name)
    if change.shared_budget_name is None:
        problem = _budget_problem(budget, change.label)
        if budget is None or problem is not None:
            reason = problem or _MISSING.format(name=change.label)
            return _Plan(budget, None, _refused(change, reason), reason)
        if change.network_priority is None:
            return _Plan(budget, None, _edits(change, budget.resource_name, removes=False), None)
        network, channel_type, problem = _network_plan(change, budget, funded)
        if problem is not None:
            return _Plan(
                budget, None, _refused(change, problem), problem, channel_type=channel_type
            )
        edits = _edits(change, budget.resource_name, removes=False, network=network)
        return _Plan(budget, None, edits, None, network=network, channel_type=channel_type)
    destination = budgets.get(change.shared_budget_name)
    target = change.use_shared_budget
    problem = _budget_problem(destination, target.label if target else "The shared budget")
    if destination is not None and not problem and not destination.shared:
        problem = _NOT_SHARED.format(name=destination.name)
    if not problem and campaign is not None and campaign.experiment_type not in {"", "BASE"}:
        problem = _EXPERIMENT
    if problem:
        return _Plan(budget, destination, _refused(change, problem), problem)
    # A budget only this campaign uses is removed with the move, unless the request changes it.
    removes = (
        budget is not None
        and budget.resource_name != change.shared_budget_name
        and not budget.shared
        and budget.reference_count == 1
        and budget.resource_name not in named_budgets
    )
    current = budget.resource_name if budget else None
    return _Plan(budget, destination, _edits(change, current, removes=removes), None, removes)


def _plans(
    changes: Sequence[GoogleAdsBudgetUpdate],
    campaigns: Mapping[str, LiveCampaign],
    budgets: Mapping[str, LiveBudget],
    funded: Sequence[BudgetCampaign],
) -> dict[str, _Plan]:
    """Plans each change; a later change to a budget an earlier one changes is a problem."""
    named = frozenset(change.resource_name for change in changes if change.budget is not None)
    # Budget entries go first, so a campaign entry is the one refused for changing their budget.
    ordered = sorted(changes, key=lambda change: change.budget is None)
    plans: dict[str, _Plan] = {}
    keys: set[str] = set()
    for change in ordered:
        plan = _plan(change, campaigns, budgets, named, funded)
        edit_keys = {edit.key for edit in plan.edits}
        if plan.problem is None and edit_keys & keys:
            name = plan.budget.name if plan.budget else change.label
            problem = _TWICE.format(name=name)
            plan = replace(plan, edits=_refused(change, problem), problem=problem)
        keys |= {edit.key for edit in plan.edits}
        plans[change.resource_name] = plan
    return plans


async def google_ads_update_budgets(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsBudgetUpdate],
        Field(
            min_length=1,
            max_length=MAX_BUDGET_UPDATES,
            description="One entry per campaign or budget, with only what changes.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateBudgetsRequest, {"changes": changes})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_key = {_reference_key(change.reference): change for change in request.changes}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_changes = [by_key[_reference_key(reference)] for reference in selected]

        async def plan(_client: GoogleAdsClient) -> EditPlan:
            owned = [
                (change, edit)
                for change in account_changes
                for edit in _approved_edits(change, shown.get(change.resource_name))
            ]
            # Spending drops before it rises.
            owned.sort(key=lambda item: _rank(item[1]))
            return [edit for _change, edit in owned], _pending_detail(entry, owned, shown)

        async def result(client: GoogleAdsClient, applied: EditResult) -> dict[str, Any]:
            return _result(entry, account_changes, shown, applied)

        return await run_approved_edits(
            ctx,
            entry,
            tool_name="google_ads_update_budgets",
            operation=_OPERATION,
            family="campaign_budgets",
            plan=plan,
            read=lambda client: _reader(client, entry),
            result=result,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.reference for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _reference_key(reference: Any) -> tuple[str, str, str]:
    # A campaign and a budget can share an ID, so the kind is part of the key.
    return (reference.customer_id, reference.entity_kind, reference.provider_entity_id)


def _rank(edit: Edit) -> int:
    """Orders decreases first and increases last, with everything else between."""
    if not isinstance(edit, FieldChange) or AMOUNT_PATH not in edit.requested:
        return 1
    before = edit.before.get(AMOUNT_PATH)
    if before is None:
        return 2
    new, old = int(edit.requested[AMOUNT_PATH]), int(before)
    return 0 if new < old else 2 if new > old else 1


def _approved_edits(change: GoogleAdsBudgetUpdate, check: Any) -> list[Edit]:
    """Builds the edits against the values the approver saw, so `apply_edits` refuses stale ones.

    The check must be for exactly this change, and any problem it showed still stands.
    """
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("requested") != change.requested
    ):
        return _refused(change, NOT_SHOWN)
    if check.get("problem"):
        return _refused(change, str(check["problem"]))
    budget = check.get("budget")
    current = budget.get("resource_name") if isinstance(budget, Mapping) else None
    values = check.get("values")
    values = values if isinstance(values, Mapping) else {}
    network = check.get("network_settings")
    edits = _edits(
        change,
        current,
        removes=check.get("removes_budget") is True,
        network=network if isinstance(network, list) else None,
    )
    if any(edit.key not in values for edit in edits):
        return _refused(change, NOT_SHOWN)
    return [replace(edit, before=edit.live(values[edit.key])) for edit in edits]


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, SettingValues]]]:
    async def read(edits: Sequence[Edit]) -> Mapping[str, SettingValues]:
        keys = [edit.key for edit in edits]
        campaigns, budgets = await _read_state(
            client,
            entry,
            campaign_ids=[key.rsplit("/", 1)[-1] for key in keys if "/campaigns/" in key],
            budget_ids=[key.rsplit("/", 1)[-1] for key in keys if "/campaignBudgets/" in key],
            network=any(
                isinstance(edit, FieldChange) and NETWORK_PATH in edit.requested for edit in edits
            ),
        )
        return {
            **{name: item.values for name, item in campaigns.items()},
            **{name: item.values for name, item in budgets.items()},
        }

    return read


async def _read_state(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    *,
    campaign_ids: Sequence[str],
    budget_ids: Sequence[str],
    network: bool,
) -> tuple[dict[str, LiveCampaign], dict[str, LiveBudget]]:
    """Reads the campaigns, then the budgets they and the request name.

    `network` also reads each budget's network order, which only a change to it needs.
    """
    login = login_customer_id(entry)
    campaigns = await read_campaigns(
        client, customer_id=entry.external_id, login_customer_id=login, campaign_ids=campaign_ids
    )
    used = [item.budget.rsplit("/", 1)[-1] for item in campaigns.values() if item.budget]
    budgets = await read_budgets(
        client,
        customer_id=entry.external_id,
        login_customer_id=login,
        budget_ids=[*budget_ids, *used],
        network=network,
    )
    return campaigns, budgets


def _pending_detail(
    entry: ResolvedContextEntry,
    owned: Sequence[tuple[GoogleAdsBudgetUpdate, Edit]],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    """Records one intent per edit, naming the change it belongs to."""
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaign_budgets:update",
                action="update_budgets",
                entity_type="google_ads_campaign_budget",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "object": edit.key,
                            "change": change.resource_name,
                            "name": _text(shown.get(change.resource_name), "name") or change.label,
                            "settings": edit.settings,
                            **{key: str(value) for key, value in change.requested.items()},
                        }
                    )
                    for change, edit in owned
                ],
            )
        ],
    )


def _text(check: Any, key: str) -> str:
    value = check.get(key) if isinstance(check, Mapping) else None
    return str(value or "")


def _result(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsBudgetUpdate],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    rows = []
    for change in changes:
        check = shown.get(change.resource_name)
        check = check if isinstance(check, Mapping) else {}
        budget = check.get("budget") if isinstance(check.get("budget"), Mapping) else {}
        # A refused change has one edit keyed by the change; otherwise the first edit is the change.
        key = (
            change.resource_name
            if change.resource_name in parents
            else _primary_key(change, budget)
        )
        parent = parents[key]
        effect = parent.effects[0] if parent.effects else None
        skipped = parent.decision == "skipped"
        outcome = (
            "already_set" if skipped else _OUTCOMES[effect.outcome if effect else "unverified"]
        )
        after = result.after.get(key)
        rows.append(
            {
                "resource_name": change.resource_name,
                "kind": "campaign" if change.campaign is not None else "budget",
                "name": _text(check, "name") or change.label,
                "budget_name": str(budget.get("name") or ""),
                "shared": budget.get("shared") is True,
                "spend_this_month": check.get("spend_this_month"),
                "read_back": skipped or after is not None,
                "settings": _setting_outcomes(change, check, after, outcome, skipped),
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {
        "account_id": entry.external_id,
        "currency": account_facts(entry).currency,
        "budgets": rows,
    }


def _primary_key(change: GoogleAdsBudgetUpdate, budget: Mapping[str, Any]) -> str:
    if change.shared_budget_name is not None:
        return change.resource_name
    return str(budget.get("resource_name") or change.resource_name)


def _setting_outcomes(
    change: GoogleAdsBudgetUpdate,
    check: Mapping[str, Any],
    after: SettingValues | None,
    outcome: str,
    skipped: bool,
) -> list[dict[str, Any]]:
    current = check.get("current") if isinstance(check.get("current"), Mapping) else {}
    names = check.get("budget_names") if isinstance(check.get("budget_names"), Mapping) else {}
    read: dict[BudgetSetting, Any] = {}
    if after is not None:
        channel_type = check.get("network_channel_type")
        read = {
            "amount": money(after.get(AMOUNT_PATH)),
            "delivery": after.get(DELIVERY_PATH),
            "shared_budget": after.get(CAMPAIGN_BUDGET_PATH),
            "network_priority": network_code(
                network_setting_for(after.get(NETWORK_PATH), channel_type)
            ),
        }
    settings = []
    for setting, requested in change.requested.items():
        before = current.get(setting)
        value = before if skipped else read.get(setting)
        named = setting == "shared_budget"
        settings.append(
            {
                "setting": setting,
                "before": names.get(before, before) if named else before,
                "requested": names.get(requested, requested) if named else requested,
                "after": names.get(value, value) if named else value,
                # With no check there is no live value to match, so null never reads as set.
                "outcome": (
                    "already_set" if setting in current and before == requested else outcome
                ),
            }
        )
    return settings


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per change, the live budget, its spend, and Google's dry run."""
    request = GoogleAdsUpdateBudgetsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsBudgetUpdate]] = defaultdict(list)
    for change in request.changes:
        by_account[change.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, changes in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), changes))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    changes: Sequence[GoogleAdsBudgetUpdate],
) -> dict[str, dict[str, Any]]:
    """Reads one account's budgets and dry runs the changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        campaigns, budgets = await _read_state(
            client,
            entry,
            campaign_ids=[c.campaign.campaign_id for c in changes if c.campaign is not None],
            budget_ids=[
                reference.budget_id
                for change in changes
                for reference in (change.budget, change.use_shared_budget)
                if reference is not None
            ],
            network=any(change.network_priority is not None for change in changes),
        )
        funded = await read_budget_campaigns(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            budgets=[name for name, budget in budgets.items() if budget.status != "REMOVED"],
        )
        plans = _plans(changes, campaigns, budgets, funded)
        rejected = await _dry_run(client, entry, plans, campaigns, budgets)
    except (IntegrationError, LookupError):
        return {change.resource_name: {"unavailable": True} for change in changes}
    today = account_facts(entry).today()
    days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    return {
        change.resource_name: _check(
            change,
            plans[change.resource_name],
            campaigns,
            budgets,
            funded,
            rejected,
            days_left,
        )
        for change in changes
    }


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    plans: Mapping[str, _Plan],
    campaigns: Mapping[str, LiveCampaign],
    budgets: Mapping[str, LiveBudget],
) -> dict[str, str]:
    """Returns Google's rejection by edit key, asking only about changes with no problem yet.

    The removal of a freed budget isn't asked about: it depends on the move, which a dry run
    doesn't make.
    """
    checked = [
        edit
        for plan in plans.values()
        if plan.problem is None
        for edit in plan.edits
        if not isinstance(edit, Removal)
    ]
    if not checked:
        return {}
    live = {
        **{name: item.values for name, item in campaigns.items()},
        **{name: item.values for name, item in budgets.items()},
    }

    async def read(edits: Sequence[Edit]) -> Mapping[str, SettingValues]:
        return {edit.key: live[edit.key] for edit in edits if edit.key in live}

    prepared = await prepare_edits(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        edits=checked,
        read=read,
        operation=_OPERATION,
    )
    # Google's message for an order that leaves a network out doesn't say what to do.
    return {
        edit.key: f"Google says: {edit.refused}"
        + (_ALL_NETWORKS if "must be assigned to a priority tier" in edit.refused else "")
        for edit in prepared
        if edit.refused
    }


def _check(
    change: GoogleAdsBudgetUpdate,
    plan: _Plan,
    campaigns: Mapping[str, LiveCampaign],
    budgets: Mapping[str, LiveBudget],
    funded: Sequence[BudgetCampaign],
    rejected: Mapping[str, str],
    days_left: int,
) -> dict[str, Any]:
    """Builds the card's view of one change, and the live values approval plans against."""
    campaign = campaigns.get(change.resource_name)
    budget, destination = plan.budget, plan.destination
    live = {
        **{name: item.values for name, item in campaigns.items()},
        **{name: item.values for name, item in budgets.items()},
    }
    problem = plan.problem or next(
        (rejected[edit.key] for edit in plan.edits if edit.key in rejected), None
    )
    moving = change.shared_budget_name is not None
    # A move shows the campaign's own spend; any other change shows its budget's.
    spenders = [
        item
        for item in funded
        if (
            item.resource_name == change.resource_name
            if moving
            else budget is not None and item.budget == budget.resource_name
        )
    ]
    return {
        "unavailable": False,
        "kind": "campaign" if change.campaign is not None else "budget",
        "name": _name(change, campaign, budget),
        "campaign_status": campaign.status if campaign else None,
        "budget": _budget_view(budget, funded),
        "destination": _budget_view(destination, funded),
        "removes_budget": plan.removes_budget,
        "spend_this_month": money(sum(item.cost_micros for item in spenders)) or "0",
        "days_left": days_left,
        "current": {
            "amount": money(budget.values.get(AMOUNT_PATH)) if budget else None,
            "delivery": budget.values.get(DELIVERY_PATH) if budget else None,
            "shared_budget": campaign.budget if campaign else None,
            "network_priority": (
                network_code(network_setting_for(budget.values[NETWORK_PATH], plan.channel_type))
                if budget and NETWORK_PATH in budget.values
                else None
            ),
        },
        # The budget's network settings once approved, in Google's terms, and their campaign type.
        "network_settings": plan.network,
        "network_channel_type": plan.channel_type,
        "budget_names": {item.resource_name: item.name for item in (budget, destination) if item},
        "requested": change.requested,
        # What approval plans against, in Google's terms, for each edit's object.
        "values": {
            edit.key: (
                edit.live(live[edit.key])
                if isinstance(edit, FieldChange)
                else {"status": live[edit.key].get("status")}
            )
            for edit in plan.edits
            if plan.problem is None and edit.key in live
        },
        "problem": problem,
    }


def _name(
    change: GoogleAdsBudgetUpdate, campaign: LiveCampaign | None, budget: LiveBudget | None
) -> str:
    if change.campaign is not None:
        return campaign.name if campaign else change.label
    return budget.name if budget else change.label


def _budget_view(
    budget: LiveBudget | None, funded: Sequence[BudgetCampaign]
) -> dict[str, Any] | None:
    if budget is None:
        return None
    campaigns = [item for item in funded if item.budget == budget.resource_name]
    return {
        "resource_name": budget.resource_name,
        "name": budget.name,
        "shared": budget.shared,
        "status": budget.status,
        "amount": money(budget.values.get(AMOUNT_PATH)),
        "delivery": budget.values.get(DELIVERY_PATH),
        "campaign_count": len(campaigns),
        "campaigns": [
            {"name": item.name, "status": item.status, "spend": money(item.cost_micros) or "0"}
            for item in campaigns[:_LISTED_CAMPAIGNS]
        ],
        "spend_this_month": money(sum(item.cost_micros for item in campaigns)) or "0",
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_budgets",
    function=google_ads_update_budgets,
    description=(
        "Change Google Ads campaign budgets, up to 100 changes per call, in one approval. "
        "Each entry names either a campaign (a google_ads_campaign reference) or a budget (a "
        "google_ads_campaign_budget reference, usually a shared one) and only what changes: "
        "amount, the new daily budget in the account currency, set on the budget the campaign "
        "uses; delivery, STANDARD or ACCELERATED; or, for a campaign, use_shared_budget, a "
        "shared budget in the same account to move it onto. A budget only that campaign used "
        "is removed with the move. Changing a shared budget changes every campaign on it, and "
        "the card lists them. Only daily budgets change here. network_priority, only when the "
        "user asks which networks a budget spends on first: first lists the networks that spend "
        "first (OWNED_AND_OPERATED is Google's own sites, SEARCH_PARTNER, GOOGLE_DISPLAY), then "
        "lists the networks that spend after them, each with an optional cap_percent of the "
        "budget (0 keeps it from spending). Every network the campaign type can show on must "
        "be in first or then: Google refuses an order that leaves one out, so never send first "
        "alone. To put Google first, send first with OWNED_AND_OPERATED and then with the "
        "other networks; or account_default to follow the account's "
        "order again. Google offers this to some accounts and budgets only, and the card says "
        "when it can't be set. The card shows each budget's spend this month from Google. Each "
        "result reports what Google Ads shows after the change."
    ),
    provider="google_ads",
    label="Update Google Ads Budgets",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsUpdateBudgetsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateBudgetsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Budgets",
        completed_label="Updated Google Ads Budgets",
        failed_label="Couldn't Update Google Ads Budgets",
        approval_title="Change Google Ads Budgets",
        approval_prompt="The agent wants to change these Google Ads budgets.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Budget Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_campaign", "google_ads_campaign_budget"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
