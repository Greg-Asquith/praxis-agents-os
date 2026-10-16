# apps/api/integrations/meta_ads/tools/update_ad_sets.py

"""Approval-only tool that changes the settings of existing Meta ad sets."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from services.integrations.approved_display_args import approved_display_args, proposed_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from utils.metadata import metadata_str

from ..client import MetaAdsClient
from ..goals import GOALS, goal_for
from ..operations.create_ad_set import read_goal_minimum
from ..operations.edit_ad_set import (
    BID_SETTINGS,
    ad_set_values,
    edit_body,
    edit_dates,
    edit_problems,
    evidence_values,
    requested_values,
)
from ..operations.edit_impact import (
    LEARNING_NOTE,
    ad_bids_note,
    count_active_ad_sets,
    count_ad_bids,
    count_recent_changes,
    daily_changes_note,
    lifetime_pace,
    minimum_spend_note,
    pace_note,
)
from ..operations.get_account import get_account
from ..operations.list_objects import read_objects_by_id
from ..operations.mutations import MetaAdsMutationLedger
from ..operations.update_fields import FieldChange, same_value, update_fields, validate_fields
from ..operations.values import minimum_budget_problem
from ..references import MetaAdsAdSetReference
from ..throttle import ensure_account_available, ensure_headroom
from ..tools.schemas.objects import MetaAdsObject
from .schemas.ad_set_edits import (
    MAX_AD_SET_EDITS,
    MetaAdsAdSetEdit,
    MetaAdsUpdateAdSetsOutput,
    MetaAdsUpdateAdSetsRequest,
)
from .utils.ad_preparation import hydrate_references, required_currency
from .utils.bindings import META_ADS_BINDING, META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client, meta_ads_client_for_principal
from .utils.create_operation import validated
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)

_OPERATION = "update_ad_sets"
_GROUP = "adsets:update-settings"
# Each ad set takes about four calls, so the run needs Meta's usage below this percentage.
_USAGE_LIMIT = 75.0
_CHANGED = (
    "This ad set changed since you approved it, so it wasn't changed. Ask the agent to "
    "prepare the change again."
)
_NOT_SHOWN = (
    "This ad set couldn't be checked before approval, so it wasn't changed. Ask the agent "
    "to prepare the change again."
)

type _Key = tuple[str, str]


@dataclass
class _Review:
    """One ad set as it is now, with what the edit would break and what it would cause."""

    edit: MetaAdsAdSetEdit
    ad_set: MetaAdsObject
    campaign: MetaAdsObject | None
    values: dict[str, str | None]
    body: dict[str, str]
    problems: list[str] = field(default_factory=list)
    # Effects that can cost results for a while, shown more prominently than notes.
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def requested(self) -> dict[str, str | None]:
        return dict(requested_values(self.edit))

    @property
    def unchanged(self) -> bool:
        return all(same_value(self.values[key], value) for key, value in self.requested.items())


@dataclass(frozen=True, slots=True)
class _Prepared:
    currency: str
    zone: ZoneInfo
    changes: list[FieldChange]


async def meta_ads_update_ad_sets(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[MetaAdsAdSetEdit],
        Field(
            min_length=1,
            max_length=MAX_AD_SET_EDITS,
            description="One entry per ad set, with only the settings that change.",
        ),
    ],
) -> dict[str, Any]:
    request = validated(MetaAdsUpdateAdSetsRequest, {"changes": changes})
    _require_proposed(proposed_args(ctx), request)
    checks = approved_display_args(ctx).get("_checks")
    shown = checks if isinstance(checks, Mapping) else {}
    edits = {_key(edit.ad_set): edit for edit in request.changes}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        client: MetaAdsClient | None = None
        prepared: _Prepared | None = None
        pending: PendingIntegrationOperationDetail | None = None
        account_edits = [edits[_key(reference)] for reference in selected]

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, prepared, pending
            ensure_account_available(entry.external_id, operation=_OPERATION)
            ensure_headroom(entry.external_id, operation=_OPERATION, limit=_USAGE_LIMIT)
            client = await meta_ads_client(ctx, entry)
            prepared = await _prepare(client, entry, account_edits, shown)
            pending = _pending_detail(entry, prepared)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or prepared is None or pending is None:
                raise RuntimeError("Meta Ads ad set edit preparation did not complete")
            try:
                ledger = await update_fields(
                    client,
                    account_id=entry.external_id,
                    currency=prepared.currency,
                    changes=prepared.changes,
                    values=lambda item: ad_set_values(item, prepared.zone),
                    action=_OPERATION,
                    group_key=_GROUP,
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_key="object_id")
                raise
            detail = terminal_operation_detail(pending, ledger, identity_key="object_id")
            result = _result(entry, prepared, ledger)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                result,
                status=status,
                external_ref=",".join(ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=result if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_update_ad_sets",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=META_ADS_WRITE_BINDING,
        references=[edit.ad_set for edit in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _key(reference: MetaAdsAdSetReference) -> _Key:
    return reference.account_id, reference.adset_id


def _require_proposed(proposed: Mapping[str, Any], request: MetaAdsUpdateAdSetsRequest) -> None:
    """The card can change values and drop settings or ad sets, but never add one."""
    try:
        original = MetaAdsUpdateAdSetsRequest.model_validate(proposed).changes
    except ValidationError:
        original = []
    settings = {_key(edit.ad_set): set(edit.settings) for edit in original}
    for edit in request.changes:
        if not set(edit.settings) <= settings.get(_key(edit.ad_set), set()):
            raise ModelRetry(
                "A setting or ad set was added after approval. Ask the agent to prepare it again."
            )


def _zone(entry: ResolvedContextEntry) -> ZoneInfo:
    try:
        return ZoneInfo(metadata_str(entry.permissions_metadata.get("timezone_name")) or "")
    except (ZoneInfoNotFoundError, ValueError):
        raise ModelRetry(
            "This ad account's time zone is unknown. Use Look for New Resources on the "
            "Meta Ads connection, then try again."
        ) from None


async def _review_account(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsAdSetEdit],
    *,
    now: datetime,
    with_notes: bool,
) -> list[_Review]:
    """Re-reads each ad set and its campaign, applies Meta's rules, and asks Meta to check."""
    account_id = entry.external_id
    currency = required_currency(entry)
    zone = _zone(entry)
    today = now.astimezone(zone).date()
    ad_sets = await read_objects_by_id(
        client,
        account_id=account_id,
        object_type="adset",
        object_ids=[edit.ad_set.adset_id for edit in edits],
        currency=currency,
    )
    if any(edit.ad_set.adset_id not in ad_sets for edit in edits):
        raise ModelRetry("Some ad sets are no longer in this ad account. Choose them again.")
    campaigns = await read_objects_by_id(
        client,
        account_id=account_id,
        object_type="campaign",
        object_ids=[item.campaign_id for item in ad_sets.values() if item.campaign_id],
        currency=currency,
    )
    reviews: list[_Review] = []
    for edit in edits:
        ad_set = ad_sets[edit.ad_set.adset_id]
        campaign = campaigns.get(ad_set.campaign_id or "")
        review = _Review(
            edit=edit,
            ad_set=ad_set,
            campaign=campaign,
            values=ad_set_values(ad_set, zone),
            body={},
        )
        if campaign is None:
            review.problems.append("This ad set's campaign couldn't be read.")
        else:
            review.problems.extend(
                edit_problems(edit, ad_set, campaign, currency=currency, zone=zone, today=today)
            )
        if not review.problems:
            review.body = edit_body(edit, currency=currency, zone=zone, now=now)
        reviews.append(review)
    await _check_paces(client, entry, reviews, currency=currency, zone=zone, today=today)
    for review in reviews:
        if review.problems or review.unchanged:
            continue
        if reason := await validate_fields(
            client,
            account_id=account_id,
            object_id=review.ad_set.id,
            body=review.body,
            operation=_OPERATION,
        ):
            review.problems.append(reason)
    if with_notes:
        await _add_notes(client, entry, reviews, currency=currency, zone=zone, now=now)
    return reviews


async def _check_paces(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    reviews: Sequence[_Review],
    *,
    currency: str,
    zone: ZoneInfo,
    today: date,
) -> None:
    """Notes a lifetime budget's new daily pace, and blocks a pace under Meta's minimum."""
    minimums: dict[str | None, str | None] = {}
    for review in reviews:
        if review.problems or review.edit.end_date in (None, "none"):
            continue
        start, end = edit_dates(review.edit, review.ad_set, zone)
        if end is None:
            continue
        pace = lifetime_pace(review.ad_set, start=start, end=end, today=today, currency=currency)
        if pace is None:
            continue
        goal = goal_for(
            review.ad_set.objective,
            review.ad_set.optimization_goal,
            review.ad_set.destination_type,
        )
        if goal not in minimums:
            minimums[goal] = await _daily_minimum(client, entry, goal, currency)
        problem = minimum_budget_problem(
            kind="lifetime",
            amount=pace.remaining,
            minimum=minimums[goal],
            days=pace.days_after,
            currency=currency,
            subject="this goal",
        )
        if problem:
            review.problems.append(f"{problem} Choose an earlier end date or raise the budget.")
        elif note := pace_note(pace, currency):
            review.notes.append(note)


async def _daily_minimum(
    client: MetaAdsClient, entry: ResolvedContextEntry, goal: Any, currency: str
) -> str | None:
    if goal is not None and (
        minimum := await read_goal_minimum(
            client, entry.external_id, GOALS[goal].minimum, currency, operation=_OPERATION
        )
    ):
        return minimum
    return (await get_account(client, account_id=entry.external_id)).min_daily_budget


async def _add_notes(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    reviews: Sequence[_Review],
    *,
    currency: str,
    zone: ZoneInfo,
    now: datetime,
) -> None:
    """Adds learning, ad bid, change frequency, and minimum spend notes for the card."""
    bids = [review for review in reviews if BID_SETTINGS.intersection(review.edit.settings)]
    for review in bids:
        if review.ad_set.learning_status is not None:
            review.warnings.append(LEARNING_NOTE)
    try:
        await _bid_notes(client, entry, bids, currency=currency, zone=zone, now=now)
        await _minimum_spend_notes(client, entry, reviews, currency=currency)
    except IntegrationError:
        # Notes are advisory, so an unreadable history or ad list doesn't hide the checks.
        return


async def _bid_notes(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    reviews: Sequence[_Review],
    *,
    currency: str,
    zone: ZoneInfo,
    now: datetime,
) -> None:
    if not reviews:
        return
    ids = [review.ad_set.id for review in reviews]
    new_bids = [review.ad_set.id for review in reviews if review.edit.bid_amount is not None]
    ad_bids = (
        await count_ad_bids(
            client, account_id=entry.external_id, currency=currency, adset_ids=new_bids
        )
        if new_bids
        else {}
    )
    midnight = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    recent = await count_recent_changes(
        client,
        account_id=entry.external_id,
        timezone_name=zone.key,
        object_ids=ids,
        since=midnight,
        now=now,
        words=("bid", "budget"),
    )
    for review in reviews:
        if note := ad_bids_note(ad_bids.get(review.ad_set.id, 0)):
            review.notes.append(note)
        if warning := daily_changes_note(recent.counts.get(review.ad_set.id, 0), recent.complete):
            review.warnings.append(warning)


async def _minimum_spend_notes(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    reviews: Sequence[_Review],
    *,
    currency: str,
) -> None:
    minimums = [
        (review, minimum)
        for review in reviews
        if review.campaign is not None
        and (minimum := review.edit.min_daily_spend or review.edit.min_lifetime_spend)
        and minimum != "remove"
    ]
    if not minimums:
        return
    active = await count_active_ad_sets(
        client,
        account_id=entry.external_id,
        currency=currency,
        campaign_ids=sorted({review.campaign.id for review, _ in minimums if review.campaign}),
    )
    for review, minimum in minimums:
        if review.campaign is not None and (
            note := minimum_spend_note(
                minimum, review.campaign, active.get(review.campaign.id, 0), currency
            )
        ):
            review.notes.append(note)


async def _prepare(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsAdSetEdit],
    shown: Mapping[str, Any],
) -> _Prepared:
    """Checks every edit again, refuses stale ones, and stops if Meta rejects any."""
    reviews = await _review_account(client, entry, edits, now=datetime.now(UTC), with_notes=False)
    if problems := [
        f"{review.ad_set.name or review.ad_set.id}: {problem}"
        for review in reviews
        for problem in review.problems
    ]:
        raise ModelRetry(
            f"These ad set changes can't be made, so nothing was changed. {' '.join(problems)}"
        )
    zone = _zone(entry)
    changes = [
        FieldChange(
            object_type="adset",
            before=review.ad_set,
            before_values={key: review.values[key] for key in review.requested},
            requested=review.requested,
            body=review.body,
            refused=_stale(review, shown.get(review.ad_set.id)),
        )
        for review in reviews
    ]
    return _Prepared(currency=required_currency(entry), zone=zone, changes=changes)


def _stale(review: _Review, shown: Any) -> str | None:
    """Refuses an edit whose settings differ from the values the approver saw."""
    before = shown.get("before") if isinstance(shown, Mapping) else None
    if not isinstance(before, Mapping):
        return _NOT_SHOWN
    for key in review.requested:
        if key not in before or not same_value(review.values[key], before[key]):
            return _CHANGED
    return None


def _pending_detail(
    entry: ResolvedContextEntry, prepared: _Prepared
) -> PendingIntegrationOperationDetail:
    items: list[IntegrationOperationIntent] = []
    for change in prepared.changes:
        keys = tuple(change.requested)
        fields = {
            "object_id": change.object_id,
            "object_name": change.before.name,
            "currency": prepared.currency,
            "before": evidence_values(dict(change.before_values), keys, prepared.currency),
            "requested": evidence_values(dict(change.requested), keys, prepared.currency),
        }
        items.append(
            IntegrationOperationIntent(
                fields={key: value for key, value in fields.items() if value is not None}
            )
        )
    return PendingIntegrationOperationDetail(
        target=meta_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=_GROUP,
                action="update_ad_set_settings",
                entity_type="meta_ads_ad_set",
                items=items,
            )
        ],
    )


def _result(
    entry: ResolvedContextEntry, prepared: _Prepared, ledger: MetaAdsMutationLedger
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object_id"]: parent for parent in ledger.parents}
    rows = []
    for change in prepared.changes:
        parent = parents[change.object_id]
        effect = parent.effects[0] if parent.effects else None
        observed = dict(effect.fields) if effect is not None else {}
        rows.append(
            {
                "adset_id": change.object_id,
                "name": change.before.name,
                "changes": [
                    {
                        "setting": key,
                        "before": change.before_values[key],
                        "requested": value,
                        "after": change.before_values[key]
                        if parent.decision == "skipped"
                        else _read_value(observed.get(f"after.{key}")),
                    }
                    for key, value in change.requested.items()
                ],
                "outcome": {"applied": "updated", "skipped": "already_set"}.get(
                    parent.outcome, parent.outcome
                ),
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "currency": prepared.currency, "ad_sets": rows}


def _read_value(value: str | None) -> str | None:
    return None if value in (None, "none") else value


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates the ad sets and adds, per ad set, its current values, problems, and notes."""
    request = MetaAdsUpdateAdSetsRequest.model_validate(args)
    hydrated = await hydrate_references(
        deps, "meta_ads_ad_set", "changes", [edit.ad_set for edit in request.changes]
    )
    changes = [
        {**dict(change), "ad_set": reference}
        for change, reference in zip(args["changes"], hydrated, strict=True)
    ]
    by_account: dict[str, list[MetaAdsAdSetEdit]] = defaultdict(list)
    for edit in request.changes:
        by_account[edit.ad_set.account_id].append(edit)
    active_context = deps.active_context
    entries = {
        entry.external_id: entry
        for entry in (active_context.compatible_entries(META_ADS_BINDING) if active_context else ())
    }
    checks: dict[str, dict[str, Any]] = {}
    for account_id, edits in by_account.items():
        checks.update(await _account_checks(deps, entries.get(account_id), edits))
    return {**args, "changes": changes, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, edits: Sequence[MetaAdsAdSetEdit]
) -> dict[str, dict[str, Any]]:
    """Checks one account's edits; any that can't be read are marked unavailable for the card."""
    try:
        if entry is None:
            raise LookupError("ad account not selected")
        client = await meta_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        reviews = await _review_account(
            client, entry, edits, now=datetime.now(UTC), with_notes=True
        )
    except (IntegrationError, LookupError, ModelRetry):
        return {edit.ad_set.adset_id: {"unavailable": True} for edit in edits}
    currency = required_currency(entry)
    return {
        review.ad_set.id: {
            "currency": currency,
            "before": review.values,
            # The values these problems were found for, so the card knows when an edit makes
            # them stale.
            "requested": review.requested,
            "problems": review.problems,
            "warnings": review.warnings,
            "notes": review.notes,
            "budget": review.ad_set.budget.model_dump(mode="json")
            if review.ad_set.budget
            else None,
            "unavailable": False,
        }
        for review in reviews
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_update_ad_sets",
    function=meta_ads_update_ad_sets,
    description=(
        "Change the settings of existing Meta ad sets, up to 50 per call, in one approval. Each "
        "entry names one ad set from meta_ads_list_objects and only the settings that change: "
        "name; start_date and end_date (YYYY-MM-DD in the account's time zone; end_date none "
        "runs a daily-budget ad set continuously, and a lifetime budget always keeps an end "
        "date); bid_strategy, only when the campaign doesn't set it, with bid_amount for bid_cap "
        "and cost_per_result_goal or min_roas for roas_goal; bid_amount or min_roas alone to "
        "change the current bid or return goal; min_daily_spend and max_daily_spend under a "
        "campaign daily budget, or min_lifetime_spend and max_lifetime_spend under a campaign "
        "lifetime budget, each an amount or remove; eu_payer and eu_beneficiary for ad sets "
        "that reach the EU. Archived and deleted ad sets can only be renamed. Change status "
        "with meta_ads_update_status and budget amounts with meta_ads_update_budgets. The card "
        "shows each new setting with its current one, and notes when a change restarts "
        "learning or replaces ad-level bids. Meta checks every change before any is made, and each result "
        "reports the values Meta shows after the change."
    ),
    provider="meta_ads",
    label="Update Meta Ad Sets",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=MetaAdsUpdateAdSetsOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Edited entries are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsUpdateAdSetsRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Updating Meta Ad Sets",
        completed_label="Updated Meta Ad Sets",
        failed_label="Couldn't Update Meta Ad Sets",
        approval_title="Change Meta Ad Set Settings",
        approval_prompt="The agent wants to change these Meta ad set settings.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes", label="Setting Changes", editable=True, format="structured"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
