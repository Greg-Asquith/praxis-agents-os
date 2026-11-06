# apps/api/integrations/meta_ads/tools/update_campaigns.py

"""Approval-only tool that changes the settings of existing Meta campaigns."""

import asyncio
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
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
from services.integrations.approved_display_args import approved_display_args, proposed_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import MetaAdsClient
from ..operations.create_campaign import read_campaign_account
from ..operations.edit_campaign import (
    campaign_values,
    edit_body,
    edit_notes,
    edit_problems,
    evidence_values,
    read_ad_sets,
    read_lifetime_spend,
    requested_values,
)
from ..operations.list_objects import read_objects_by_id
from ..operations.mutations import MetaAdsMutationLedger
from ..operations.update_fields import (
    FieldChange,
    SettingValues,
    same_value,
    update_fields,
    validate_fields,
)
from ..references import MetaAdsCampaignReference
from ..throttle import ensure_account_available, ensure_headroom
from ..tools.schemas.objects import MetaAdsObject
from .schemas.campaign_edits import (
    MAX_CAMPAIGN_EDITS,
    MetaAdsCampaignEdit,
    MetaAdsUpdateCampaignsOutput,
    MetaAdsUpdateCampaignsRequest,
)
from .utils.ad_preparation import hydrate_references, required_currency
from .utils.bindings import META_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import (
    meta_ads_available,
    meta_ads_client,
    meta_ads_client_for_principal,
    meta_ads_entries,
)
from .utils.create_operation import validated
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    meta_ads_account_target,
    terminal_operation_detail,
)

_OPERATION = "update_campaigns"
_GROUP = "campaigns:update-settings"
# Each campaign takes a few reads and two posts, so the run needs Meta's usage below this.
_USAGE_LIMIT = 75.0
_CHANGED = (
    "This campaign changed since you approved it, so it wasn't changed. Ask the agent to "
    "prepare the change again."
)
_NOT_SHOWN = (
    "This campaign couldn't be checked before approval, so it wasn't changed. Ask the agent "
    "to prepare the change again."
)

type _Key = tuple[str, str]


@dataclass
class _Review:
    """One campaign as it is now, with what the edit would break and what it would cause."""

    edit: MetaAdsCampaignEdit
    campaign: MetaAdsObject
    # The campaign's ad sets that aren't deleted, read when the bid strategy changes.
    ad_sets: list[MetaAdsObject]
    values: dict[str, str | None]
    requested: dict[str, str | None]
    body: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    # Effects that can cost results for a while, shown more prominently than notes.
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Lifetime spend in the account currency, read when the spending limit changes.
    spent: str | None = None

    @property
    def unchanged(self) -> bool:
        return all(same_value(self.values[key], value) for key, value in self.requested.items())


@dataclass(frozen=True, slots=True)
class _Prepared:
    currency: str
    changes: list[FieldChange]
    # Ad set names for the result's bid rows, by ad set ID.
    ad_set_names: dict[str, str | None]


async def meta_ads_update_campaigns(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[MetaAdsCampaignEdit],
        Field(
            min_length=1,
            max_length=MAX_CAMPAIGN_EDITS,
            description="One entry per campaign, with only the settings that change.",
        ),
    ],
) -> dict[str, Any]:
    request = validated(MetaAdsUpdateCampaignsRequest, {"changes": changes})
    _require_proposed(proposed_args(ctx), request)
    checks = approved_display_args(ctx).get("_checks")
    shown = checks if isinstance(checks, Mapping) else {}
    edits = {_key(edit.campaign): edit for edit in request.changes}

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
                raise RuntimeError("Meta Ads campaign edit preparation did not complete")
            try:
                ledger = await update_fields(
                    client,
                    account_id=entry.external_id,
                    currency=prepared.currency,
                    changes=prepared.changes,
                    read=lambda ids: _read_back(client, entry, prepared, ids),
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
            tool_name="meta_ads_update_campaigns",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=META_ADS_WRITE_BINDING,
        references=[edit.campaign for edit in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _key(reference: MetaAdsCampaignReference) -> _Key:
    return reference.account_id, reference.campaign_id


def _require_proposed(proposed: Mapping[str, Any], request: MetaAdsUpdateCampaignsRequest) -> None:
    """The card can change values and drop settings or campaigns, but never add one."""
    try:
        original = MetaAdsUpdateCampaignsRequest.model_validate(proposed).changes
    except ValidationError:
        original = []
    settings = {_key(edit.campaign): _proposal(edit) for edit in original}
    for edit in request.changes:
        if not _proposal(edit) <= settings.get(_key(edit.campaign), set()):
            raise ModelRetry(
                "A setting, ad set bid, or campaign was added after approval. Ask the agent to "
                "prepare it again."
            )


def _proposal(edit: MetaAdsCampaignEdit) -> set[str]:
    """The settings an edit proposes, with each ad set it bids on."""
    return {*edit.settings, *(f"bid:{bid.ad_set.adset_id}" for bid in edit.ad_set_bids)}


async def _review_account(
    client: MetaAdsClient, entry: ResolvedContextEntry, edits: Sequence[MetaAdsCampaignEdit]
) -> list[_Review]:
    """Re-reads each campaign, its ad sets, and its spend, applies Meta's rules, and asks Meta."""
    account_id = entry.external_id
    currency = required_currency(entry)
    campaigns = await read_objects_by_id(
        client,
        account_id=account_id,
        object_type="campaign",
        object_ids=[edit.campaign.campaign_id for edit in edits],
        currency=currency,
    )
    if any(edit.campaign.campaign_id not in campaigns for edit in edits):
        raise ModelRetry("Some campaigns are no longer in this ad account. Choose them again.")
    bidding = [edit.campaign.campaign_id for edit in edits if edit.bid_strategy is not None]
    ad_sets = (
        await read_ad_sets(client, account_id=account_id, currency=currency, campaign_ids=bidding)
        if bidding
        else {}
    )
    limited = [edit.campaign.campaign_id for edit in edits if edit.spend_limit is not None]
    spent = (
        await read_lifetime_spend(
            client, account_id=account_id, campaign_ids=limited, operation=_OPERATION
        )
        if limited
        else {}
    )
    minimum = (
        (
            await read_campaign_account(client, account_id=account_id, operation=_OPERATION)
        ).minimum_spend_limit
        if any(edit.spend_limit not in (None, "remove") for edit in edits)
        else None
    )
    reviews = [
        _review(edit, campaigns[edit.campaign.campaign_id], ad_sets, spent, currency, minimum)
        for edit in edits
    ]
    for review in reviews:
        if review.problems or review.unchanged:
            continue
        if reason := await validate_fields(
            client,
            account_id=account_id,
            object_id=review.campaign.id,
            body=review.body,
            operation=_OPERATION,
        ):
            review.problems.append(reason)
    return reviews


def _review(
    edit: MetaAdsCampaignEdit,
    campaign: MetaAdsObject,
    ad_sets: Mapping[str, list[MetaAdsObject]],
    spent: Mapping[str, str],
    currency: str,
    minimum: str | None,
) -> _Review:
    children = ad_sets.get(campaign.id, [])
    review = _Review(
        edit=edit,
        campaign=campaign,
        ad_sets=children,
        values=campaign_values(campaign, _bids(edit, children)),
        requested=dict(requested_values(edit, currency)),
        spent=spent.get(campaign.id),
    )
    review.problems = edit_problems(
        edit,
        campaign,
        children,
        currency=currency,
        spent=review.spent,
        minimum_spend_limit=minimum,
    )
    if not review.problems:
        review.body = edit_body(edit, currency=currency)
    review.warnings, review.notes = edit_notes(edit, campaign)
    return review


def _bids(
    edit: MetaAdsCampaignEdit, ad_sets: Sequence[MetaAdsObject]
) -> dict[str, str | None] | None:
    """The current bid of each ad set the edit names; None when it names none."""
    if not edit.ad_set_bids:
        return None
    current = {item.id: item.bid_amount for item in ad_sets}
    return {bid.ad_set.adset_id: current.get(bid.ad_set.adset_id) for bid in edit.ad_set_bids}


async def _prepare(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsCampaignEdit],
    shown: Mapping[str, Any],
) -> _Prepared:
    """Checks every edit again, refuses stale ones, and stops if Meta rejects any."""
    reviews = await _review_account(client, entry, edits)
    if problems := [
        f"{review.campaign.name or review.campaign.id}: {problem}"
        for review in reviews
        for problem in review.problems
    ]:
        raise ModelRetry(
            f"These campaign changes can't be made, so nothing was changed. {' '.join(problems)}"
        )
    changes = [
        FieldChange(
            object_type="campaign",
            before=review.campaign,
            before_values={key: review.values[key] for key in review.requested},
            requested=review.requested,
            body=review.body,
            refused=_stale(review, shown.get(review.campaign.id)),
        )
        for review in reviews
    ]
    return _Prepared(
        currency=required_currency(entry),
        changes=changes,
        ad_set_names={item.id: item.name for review in reviews for item in review.ad_sets},
    )


def _stale(review: _Review, shown: Any) -> str | None:
    """Refuses an edit whose settings differ from the values the approver saw."""
    before = shown.get("before") if isinstance(shown, Mapping) else None
    if not isinstance(before, Mapping):
        return _NOT_SHOWN
    for key in review.requested:
        if key not in before or not same_value(review.values[key], before[key]):
            return _CHANGED
    return None


async def _read_back(
    client: MetaAdsClient, entry: ResolvedContextEntry, prepared: _Prepared, ids: Sequence[str]
) -> dict[str, SettingValues]:
    """Reads the changed campaigns again, with the bids of the ad sets each change named."""
    currency = prepared.currency
    campaigns = await read_objects_by_id(
        client,
        account_id=entry.external_id,
        object_type="campaign",
        object_ids=ids,
        currency=currency,
    )
    named = {
        change.object_id: list(json.loads(change.requested["ad_set_bids"] or "{}"))
        for change in prepared.changes
        if change.object_id in campaigns and "ad_set_bids" in change.requested
    }
    ad_sets = (
        await read_ad_sets(
            client, account_id=entry.external_id, currency=currency, campaign_ids=list(named)
        )
        if named
        else {}
    )
    values: dict[str, SettingValues] = {}
    for campaign_id, campaign in campaigns.items():
        bids = None
        if campaign_id in named:
            current = {item.id: item.bid_amount for item in ad_sets.get(campaign_id, [])}
            bids = {adset_id: current.get(adset_id) for adset_id in named[campaign_id]}
        values[campaign_id] = campaign_values(campaign, bids)
    return values


def _pending_detail(
    entry: ResolvedContextEntry, prepared: _Prepared
) -> PendingIntegrationOperationDetail:
    items: list[IntegrationOperationIntent] = []
    for change in prepared.changes:
        fields = {
            "object_id": change.object_id,
            "object_name": change.before.name,
            "currency": prepared.currency,
            "before": evidence_values(change.before_values, prepared.currency),
            "requested": evidence_values(change.requested, prepared.currency),
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
                action="update_campaign_settings",
                entity_type="meta_ads_campaign",
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
        skipped = parent.decision == "skipped"
        after = {
            key: change.before_values[key] if skipped else _read_value(observed.get(f"after.{key}"))
            for key in change.requested
        }
        rows.append(
            {
                "campaign_id": change.object_id,
                "name": change.before.name,
                "changes": [
                    {
                        "setting": key,
                        "before": change.before_values[key],
                        "requested": value,
                        "after": after[key],
                    }
                    for key, value in change.requested.items()
                    if key != "ad_set_bids"
                ],
                "ad_set_bids": _bid_rows(change, after.get("ad_set_bids"), prepared.ad_set_names),
                "outcome": {"applied": "updated", "skipped": "already_set"}.get(
                    parent.outcome, parent.outcome
                ),
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "currency": prepared.currency, "campaigns": rows}


def _bid_rows(
    change: FieldChange, after: str | None, names: Mapping[str, str | None]
) -> list[dict[str, Any]]:
    requested = change.requested.get("ad_set_bids")
    if requested is None:
        return []
    before = json.loads(change.before_values.get("ad_set_bids") or "{}")
    read = json.loads(after) if after else {}
    return [
        {
            "adset_id": adset_id,
            "name": names.get(adset_id),
            "before": before.get(adset_id),
            "requested": bid,
            "after": read.get(adset_id),
        }
        for adset_id, bid in json.loads(requested).items()
    ]


def _read_value(value: str | None) -> str | None:
    return None if value in (None, "none") else value


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates the campaigns and adds, per campaign, its current values, problems, and notes."""
    request = MetaAdsUpdateCampaignsRequest.model_validate(args)
    hydrated = await hydrate_references(
        deps, "meta_ads_campaign", "changes", [edit.campaign for edit in request.changes]
    )
    changes = [
        {**dict(change), "campaign": reference}
        for change, reference in zip(args["changes"], hydrated, strict=True)
    ]
    by_account: dict[str, list[MetaAdsCampaignEdit]] = defaultdict(list)
    for edit in request.changes:
        by_account[edit.campaign.account_id].append(edit)
    entries = meta_ads_entries(deps)
    checks: dict[str, dict[str, Any]] = {}
    for account_id, edits in by_account.items():
        checks.update(await _account_checks(deps, entries.get(account_id), edits))
    return {**args, "changes": changes, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, edits: Sequence[MetaAdsCampaignEdit]
) -> dict[str, dict[str, Any]]:
    """Checks one account's edits; any that can't be read are marked unavailable for the card."""
    try:
        if entry is None:
            raise LookupError("ad account not selected")
        client = await meta_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        reviews = await _review_account(client, entry, edits)
    except (IntegrationError, LookupError, ModelRetry):
        return {edit.campaign.campaign_id: {"unavailable": True} for edit in edits}
    currency = required_currency(entry)
    return {
        review.campaign.id: {
            "currency": currency,
            "before": review.values,
            # The values these problems were found for, so the card knows when an edit makes
            # them stale.
            "requested": review.requested,
            "problems": review.problems,
            "warnings": review.warnings,
            "notes": review.notes,
            "spent": review.spent,
            "budget": review.campaign.budget.model_dump(mode="json")
            if review.campaign.budget
            else None,
            "ad_sets": [
                {"id": item.id, "name": item.name or item.id, "bid": item.bid_amount}
                for item in review.ad_sets
            ],
            "unavailable": False,
        }
        for review in reviews
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_update_campaigns",
    function=meta_ads_update_campaigns,
    description=(
        "Change the settings of existing Meta campaigns, up to 50 per call, in one approval. "
        "Each entry names one campaign from meta_ads_list_objects and only the settings that "
        "change: name; spend_limit, an amount for the most the campaign spends over its life, "
        "above what it has spent so far, or remove; bid_strategy, only for a campaign that "
        "holds the budget, with ad_set_bids (one bid_amount for every ad set in the campaign "
        "that isn't deleted) for bid_cap and cost_per_result_goal, and none for "
        "highest_volume; share_between_ad_sets false, to stop ad sets with their own budgets "
        "sharing them (it can't be turned back on). A campaign can't move to or leave "
        "roas_goal here. Archived and deleted campaigns can only be renamed. Change status "
        "with meta_ads_update_status, budget amounts with meta_ads_update_budgets, and an ad "
        "set budget campaign's bid strategies and end dates with meta_ads_update_ad_sets. "
        "Objective and buying type never change: copy the campaign or create a new one. The "
        "card shows each new setting with its current one and the campaign's spend so far. "
        "Meta checks every change before any is made, and each result reports the values Meta "
        "shows after the change."
    ),
    provider="meta_ads",
    label="Update Meta Campaigns",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=MetaAdsUpdateCampaignsOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Edited entries are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsUpdateCampaignsRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Updating Meta Campaigns",
        completed_label="Updated Meta Campaigns",
        failed_label="Couldn't Update Meta Campaigns",
        approval_title="Change Meta Campaign Settings",
        approval_prompt="The agent wants to change these Meta campaign settings.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes", label="Setting Changes", editable=True, format="structured"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
