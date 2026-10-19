# apps/api/integrations/meta_ads/tools/update_targeting.py

"""Approval-only tool that changes who existing Meta ad sets reach."""

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.report_results import ReportResultBudget

from ..client import MetaAdsClient, ad_account_path
from ..entity_resolvers.utils import asset_read_args
from ..operations.create_ad_set import LEGACY_ADVANTAGE_TYPES, includes_eu, special_category
from ..operations.edit_ad_set import LEGACY_ADVANTAGE
from ..operations.edit_impact import LEARNING_NOTE, TARGETING_REVIEW_NOTE, narrow_audience_note
from ..operations.edit_targeting import MetaAdsTargetingChange, edit_targeting
from ..operations.estimate_audience import estimate_spec
from ..operations.list_assets import read_audience_references
from ..operations.list_objects import read_objects_by_id
from ..operations.mutations import MetaAdsMutationLedger
from ..operations.targeting_reader import (
    MetaAdsReadTargeting,
    read_targeting,
    read_targeting_specs,
    section_fingerprints,
    section_values,
)
from ..operations.update_fields import FieldChange, SettingValues, update_fields, validate_fields
from ..references import MetaAdsAdSetReference, MetaAdsAudienceReference
from ..throttle import ensure_account_available, ensure_headroom
from .schemas.objects import CLOSED_STATUSES, MetaAdsObject
from .schemas.targeting_edits import (
    MAX_TARGETING_EDITS,
    MetaAdsTargetingEdit,
    MetaAdsUpdateTargetingOutput,
    MetaAdsUpdateTargetingRequest,
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

_OPERATION = "update_targeting"
_GROUP = "adsets:update-targeting"
# Each ad set takes about four calls, so the run needs Meta's usage below this percentage.
_USAGE_LIMIT = 75.0
# The card waits this long in total for Meta's audience estimates, before and after.
_ESTIMATE_SECONDS = 20.0
_ESTIMATE_SKIPPED = "Meta's audience estimate took too long, so the card doesn't show it."
_CHANGED = (
    "This ad set's targeting changed since you approved it, so it wasn't changed. Ask the "
    "agent to prepare the change again."
)
_NOT_SHOWN = (
    "This ad set couldn't be checked before approval, so it wasn't changed. Ask the agent "
    "to prepare the change again."
)
# Additions and removals, counted in evidence.
_LIST_OPERATIONS = (
    "add_locations",
    "remove_locations",
    "add_excluded_locations",
    "remove_excluded_locations",
    "remove_detailed_items",
    "add_audiences",
    "remove_audiences",
    "add_excluded_audiences",
    "remove_excluded_audiences",
)

type _Key = tuple[str, str]


@dataclass
class _Review:
    """One ad set's targeting as it is now, with what the edit would break and cause."""

    edit: MetaAdsTargetingEdit
    ad_set: MetaAdsObject
    # Housing, employment, and financial campaigns limit targeting.
    special_category: bool = False
    read: MetaAdsReadTargeting | None = None
    change: MetaAdsTargetingChange | None = None
    problems: list[str] = field(default_factory=list)
    # Effects that can cost results for a while, shown more prominently than notes.
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Meta's estimate before and after, as lower and upper bounds; None when there's none.
    estimates: dict[str, dict[str, int] | None] = field(default_factory=dict)

    @property
    def before(self) -> SettingValues:
        return _values(self, before=True)

    @property
    def requested(self) -> SettingValues:
        return _values(self, before=False)

    @property
    def body(self) -> dict[str, str]:
        if self.change is None:
            return {}
        body = {"targeting": json.dumps(self.change.spec)}
        if self.edit.eu_payer is not None:
            body["dsa_payor"] = self.edit.eu_payer
        if self.edit.eu_beneficiary is not None:
            body["dsa_beneficiary"] = self.edit.eu_beneficiary
        return body


def _values(review: _Review, *, before: bool) -> SettingValues:
    change = review.change
    if change is None:
        return {}
    values = section_values(change.before if before else change.after)
    return {section: values[section] for section in change.sections}


async def meta_ads_update_targeting(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[MetaAdsTargetingEdit],
        Field(
            min_length=1,
            max_length=MAX_TARGETING_EDITS,
            description="One entry per ad set, with only the targeting that changes.",
        ),
    ],
) -> dict[str, Any]:
    request = validated(MetaAdsUpdateTargetingRequest, {"changes": changes})
    _require_proposed(proposed_args(ctx), request)
    checks = approved_display_args(ctx).get("_checks")
    shown = checks if isinstance(checks, Mapping) else {}
    edits = {_key(edit.ad_set): edit for edit in request.changes}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        client: MetaAdsClient | None = None
        prepared: list[FieldChange] = []
        reviews: list[_Review] = []
        pending: PendingIntegrationOperationDetail | None = None
        account_edits = [edits[_key(reference)] for reference in selected]

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, prepared, reviews, pending
            ensure_account_available(entry.external_id, operation=_OPERATION)
            ensure_headroom(entry.external_id, operation=_OPERATION, limit=_USAGE_LIMIT)
            client = await meta_ads_client(ctx, entry)
            reviews, prepared = await _prepare(client, entry, account_edits, shown)
            pending = _pending_detail(entry, reviews)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None:
                raise RuntimeError("Meta Ads targeting edit preparation did not complete")
            account_client = client
            try:
                ledger = await update_fields(
                    client,
                    account_id=entry.external_id,
                    currency=required_currency(entry),
                    changes=prepared,
                    action=_OPERATION,
                    group_key=_GROUP,
                    operation=_OPERATION,
                    read=lambda ids: _read_sections(account_client, entry.external_id, ids),
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_key="object_id")
                raise
            detail = terminal_operation_detail(pending, ledger, identity_key="object_id")
            result = _result(entry, reviews, ledger)
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
            tool_name="meta_ads_update_targeting",
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


def _require_proposed(proposed: Mapping[str, Any], request: MetaAdsUpdateTargetingRequest) -> None:
    """The card can change values, drop changes or ad sets, and add or remove places and
    audiences, but never add an ad set or any other change."""
    try:
        original = MetaAdsUpdateTargetingRequest.model_validate(proposed).changes
    except ValidationError:
        original = []
    proposals = {_key(edit.ad_set): _proposal(edit) for edit in original}
    for edit in request.changes:
        key = _key(edit.ad_set)
        if key not in proposals or not _proposal(edit) <= proposals[key]:
            raise ModelRetry(
                "A targeting change or ad set was added after approval. Ask the agent to "
                "prepare it again."
            )


def _proposal(edit: MetaAdsTargetingEdit) -> set[tuple[str, ...]]:
    """The detailed items an edit adds or removes, and the settings it sets to any value."""
    items: set[tuple[str, ...]] = set()
    for item in edit.remove_detailed_items:
        items.add(("remove_detailed_items", item))
    if edit.add_detailed_items is not None:
        items.update(("add_detailed_items", item.key) for item in edit.add_detailed_items.items)
    for name in MetaAdsTargetingEdit.model_fields:
        value = getattr(edit, name)
        if name not in (*_LIST_OPERATIONS, "ad_set", "add_detailed_items") and value is not None:
            items.add((name,))
    return items


async def _review_account(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsTargetingEdit],
    *,
    with_notes: bool,
) -> list[_Review]:
    """Re-reads each ad set and its targeting, applies the edit with Meta's rules, and asks Meta."""
    account_id = entry.external_id
    currency = required_currency(entry)
    ids = [edit.ad_set.adset_id for edit in edits]
    ad_sets = await read_objects_by_id(
        client, account_id=account_id, object_type="adset", object_ids=ids, currency=currency
    )
    if any(adset_id not in ad_sets for adset_id in ids):
        raise ModelRetry("Some ad sets are no longer in this ad account. Choose them again.")
    campaigns = await read_objects_by_id(
        client,
        account_id=account_id,
        object_type="campaign",
        object_ids=[item.campaign_id for item in ad_sets.values() if item.campaign_id],
        currency=currency,
    )
    specs = await read_targeting_specs(client, account_id=account_id, adset_ids=ids)
    audiences = await _read_audiences(client, entry, edits, specs.values())
    eu_defaults = any("locations" in edit.sections for edit in edits) and await _has_eu_defaults(
        client, account_id
    )
    reviews: list[_Review] = []
    for edit in edits:
        review = _Review(edit=edit, ad_set=ad_sets[edit.ad_set.adset_id])
        campaign = campaigns.get(review.ad_set.campaign_id or "")
        review.special_category = campaign is not None and special_category(campaign)
        review.problems.extend(_ad_set_problems(review, campaign, specs, audiences))
        if not review.problems:
            _apply(review, specs[review.ad_set.id], audiences, eu_defaults=eu_defaults)
        reviews.append(review)
    for review in reviews:
        if review.problems or review.requested == review.before:
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
        await _add_notes(client, account_id, reviews)
    return reviews


def _ad_set_problems(
    review: _Review,
    campaign: MetaAdsObject | None,
    specs: Mapping[str, dict[str, Any]],
    audiences: Mapping[str, MetaAdsAudienceReference],
) -> list[str]:
    if campaign is None:
        return ["This ad set's campaign couldn't be read."]
    if campaign.smart_promotion_type in LEGACY_ADVANTAGE_TYPES:
        return [LEGACY_ADVANTAGE]
    if review.ad_set.status in CLOSED_STATUSES:
        return ["This ad set is archived or deleted, so its targeting can't change."]
    if review.ad_set.id not in specs:
        return ["This ad set's targeting couldn't be read."]
    edit = review.edit
    return [
        f"This ad account can't use {item.label}. Choose one from meta_ads_list_assets."
        for item in (*edit.add_audiences, *edit.add_excluded_audiences)
        if item.audience_id not in audiences
    ]


def _apply(
    review: _Review,
    spec: dict[str, Any],
    audiences: Mapping[str, MetaAdsAudienceReference],
    *,
    eu_defaults: bool,
) -> None:
    ad_set = review.ad_set
    review.read = read_targeting(
        spec, account_id=review.edit.ad_set.account_id, audiences=audiences
    )
    review.change = edit_targeting(
        review.edit,
        review.read,
        special_category=review.special_category,
        reached_eu=includes_eu(ad_set.countries or ()),
        has_eu_names=bool(ad_set.eu_payer and ad_set.eu_beneficiary),
        eu_defaults=eu_defaults,
    )
    review.problems.extend(review.change.problems)
    review.notes.extend(review.change.notes)


async def _read_audiences(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsTargetingEdit],
    specs: Iterable[Mapping[str, Any]],
) -> dict[str, MetaAdsAudienceReference]:
    """Reads the account's audiences that the ad sets use or the edits add, by ID."""
    wanted = {
        item.audience_id
        for edit in edits
        for item in (*edit.add_audiences, *edit.add_excluded_audiences)
    }
    for spec in specs:
        for key in ("custom_audiences", "excluded_custom_audiences"):
            rows = spec.get(key)
            if isinstance(rows, list):
                wanted.update(
                    row["id"]
                    for row in rows
                    if isinstance(row, dict) and isinstance(row.get("id"), str)
                )
    if not wanted:
        return {}
    found, _more = await read_audience_references(
        client,
        **asset_read_args(entry, ReportResultBudget("meta_ads", _OPERATION)),
        audience_ids=sorted(wanted),
    )
    return {item.audience_id: item for item in found}


async def _has_eu_defaults(client: MetaAdsClient, account_id: str) -> bool:
    """Checks whether the ad account names a default EU payer and beneficiary."""
    ensure_account_available(account_id, operation=_OPERATION)
    raw = await client.graph_get(
        ad_account_path(account_id),
        params={"fields": "default_dsa_payor,default_dsa_beneficiary"},
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        usage_account_id=account_id,
    )
    return all(
        isinstance(raw.get(key), str) and raw[key].strip()
        for key in ("default_dsa_payor", "default_dsa_beneficiary")
    )


async def _add_notes(client: MetaAdsClient, account_id: str, reviews: Sequence[_Review]) -> None:
    """Adds learning and review notes, and Meta's audience estimates within a time budget."""
    deadline = time.monotonic() + _ESTIMATE_SECONDS
    for review in reviews:
        if review.problems or review.change is None or review.read is None:
            continue
        if review.ad_set.learning_status is not None:
            review.warnings.append(LEARNING_NOTE)
        review.notes.append(TARGETING_REVIEW_NOTE)
        try:
            for when, spec in (("before", review.read.spec), ("after", review.change.spec)):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                estimate = await asyncio.wait_for(
                    estimate_spec(client, account_id=account_id, spec=spec), remaining
                )
                lower, upper = estimate.users_lower_bound, estimate.users_upper_bound
                review.estimates[when] = (
                    None if lower is None or upper is None else {"lower": lower, "upper": upper}
                )
        except TimeoutError:
            review.notes.append(_ESTIMATE_SKIPPED)
            continue
        except IntegrationError:
            # Estimates are advisory, so an unreadable one doesn't hide the checks.
            continue
        after = review.estimates.get("after")
        if after and (note := narrow_audience_note(after["lower"], after["upper"])):
            review.notes.append(note)


async def _prepare(
    client: MetaAdsClient,
    entry: ResolvedContextEntry,
    edits: Sequence[MetaAdsTargetingEdit],
    shown: Mapping[str, Any],
) -> tuple[list[_Review], list[FieldChange]]:
    """Checks every edit again, refuses stale ones, and stops if Meta rejects any."""
    reviews = await _review_account(client, entry, edits, with_notes=False)
    if problems := [
        f"{review.ad_set.name or review.ad_set.id}: {problem}"
        for review in reviews
        for problem in review.problems
    ]:
        raise ModelRetry(
            f"These targeting changes can't be made, so nothing was changed. {' '.join(problems)}"
        )
    changes = [
        FieldChange(
            object_type="adset",
            before=review.ad_set,
            before_values=review.before,
            requested=review.requested,
            body=review.body,
            refused=_stale(review, shown.get(review.ad_set.id)),
        )
        for review in reviews
    ]
    return reviews, changes


def _stale(review: _Review, shown: Any) -> str | None:
    """Refuses an edit whose touched sections differ from the targeting the approver saw."""
    sections = shown.get("sections") if isinstance(shown, Mapping) else None
    if not isinstance(sections, Mapping) or review.read is None or review.change is None:
        return _NOT_SHOWN
    current = section_fingerprints(review.read.spec)
    for section in review.change.sections:
        if sections.get(section) != current[section]:
            return _CHANGED
    return None


async def _read_sections(
    client: MetaAdsClient, account_id: str, adset_ids: Sequence[str]
) -> dict[str, SettingValues]:
    """Reads each ad set's targeting back, described by keys like the requested values."""
    specs = await read_targeting_specs(client, account_id=account_id, adset_ids=adset_ids)
    return {
        adset_id: section_values(read_targeting(spec, account_id=account_id).draft)
        for adset_id, spec in specs.items()
    }


def _pending_detail(
    entry: ResolvedContextEntry, reviews: Sequence[_Review]
) -> PendingIntegrationOperationDetail:
    items = []
    for review in reviews:
        edit = review.edit
        operations = {
            name: len(getattr(edit, name)) for name in _LIST_OPERATIONS if getattr(edit, name)
        }
        if edit.add_detailed_items is not None:
            operations["add_detailed_items"] = len(edit.add_detailed_items.items)
        fields = {
            "object_id": review.ad_set.id,
            "object_name": review.ad_set.name,
            "sections": list(review.change.sections) if review.change else [],
            "operations": operations,
            "eu_names": review.change.eu_names if review.change else None,
            "before": dict(review.before),
            "requested": dict(review.requested),
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
                action="update_ad_set_targeting",
                entity_type="meta_ads_ad_set",
                items=items,
            )
        ],
    )


def _result(
    entry: ResolvedContextEntry, reviews: Sequence[_Review], ledger: MetaAdsMutationLedger
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object_id"]: parent for parent in ledger.parents}
    rows = []
    for review in reviews:
        change = review.change
        if change is None:
            continue
        parent = parents[review.ad_set.id]
        effect = parent.effects[0] if parent.effects else None
        observed = dict(effect.fields) if effect is not None else {}
        before, requested = review.before, review.requested
        rows.append(
            {
                "adset_id": review.ad_set.id,
                "name": review.ad_set.name,
                "before": change.before.model_dump(mode="json"),
                "requested": change.after.model_dump(mode="json"),
                "changes": [
                    {
                        "section": section,
                        "before": before[section],
                        "requested": requested[section],
                        "after": before[section]
                        if parent.decision == "skipped"
                        else observed.get(f"after.{section}"),
                    }
                    for section in change.sections
                ],
                "outcome": {"applied": "updated", "skipped": "already_set"}.get(
                    parent.outcome, parent.outcome
                ),
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "ad_sets": rows}


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Hydrates the ad sets and adds, per ad set, its targeting before and after, and checks."""
    request = MetaAdsUpdateTargetingRequest.model_validate(args)
    hydrated = await hydrate_references(
        deps, "meta_ads_ad_set", "changes", [edit.ad_set for edit in request.changes]
    )
    changes = [
        {**dict(change), "ad_set": reference}
        for change, reference in zip(args["changes"], hydrated, strict=True)
    ]
    by_account: dict[str, list[MetaAdsTargetingEdit]] = defaultdict(list)
    for edit in request.changes:
        by_account[edit.ad_set.account_id].append(edit)
    entries = meta_ads_entries(deps)
    checks: dict[str, dict[str, Any]] = {}
    for account_id, edits in by_account.items():
        checks.update(await _account_checks(deps, entries.get(account_id), edits))
    for change, edit in zip(args["changes"], request.changes, strict=True):
        # The entry these checks were made for, so the card knows when its own edits outdate them.
        requested = {key: value for key, value in dict(change).items() if key != "ad_set"}
        checks.get(edit.ad_set.adset_id, {})["requested"] = requested
    return {**args, "changes": changes, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps, entry: ResolvedContextEntry | None, edits: Sequence[MetaAdsTargetingEdit]
) -> dict[str, dict[str, Any]]:
    """Checks one account's edits; any that can't be read are marked unavailable for the card."""
    try:
        if entry is None:
            raise LookupError("ad account not selected")
        client = await meta_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        reviews = await _review_account(client, entry, edits, with_notes=True)
    except (IntegrationError, LookupError, ModelRetry):
        return {edit.ad_set.adset_id: {"unavailable": True} for edit in edits}
    return {review.ad_set.id: _check(review) for review in reviews}


def _check(review: _Review) -> dict[str, Any]:
    read, change = review.read, review.change
    return {
        "unavailable": False,
        "before": read.draft.model_dump(mode="json") if read else None,
        "after": change.after.model_dump(mode="json") if change else None,
        "sections": section_fingerprints(read.spec) if read else {},
        "unmodelled": read.unmodelled if read else {},
        "special_category": review.special_category,
        "estimates": review.estimates,
        "problems": review.problems,
        "warnings": review.warnings,
        "notes": review.notes,
    }


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_update_targeting",
    function=meta_ads_update_targeting,
    description=(
        "Change who existing Meta ad sets reach, up to 20 per call, in one approval. Each entry "
        "names one ad set from meta_ads_list_objects and only what changes, as additions and "
        "removals; the tool never takes a whole targeting spec. add_locations and "
        "add_excluded_locations take places from meta_ads_search_targeting; remove_locations "
        "and remove_excluded_locations take kind and key of places the ad set already has. "
        "location_types home_or_recent or home; age_min and age_max (13 to 65, age_max none "
        "for 65 and over); genders all, men, or women; languages replaces the language keys, "
        "or all; detailed replaces every detailed group, or none; add_detailed_items adds "
        "items to group 1 to 5 (one more than the last starts a new group), and "
        "remove_detailed_items removes keys; add_audiences, remove_audiences, "
        "add_excluded_audiences, and remove_excluded_audiences take audiences from "
        "meta_ads_list_assets in the ad set's ad account; advantage_audience on or off; "
        "eu_payer and eu_beneficiary when an ad set newly reaches the EU and the account has "
        "no defaults. Adding something already there, or removing something that isn't, is "
        "an error. Settings Praxis doesn't model, such as pin locations, stay as they are, "
        "and a change to a section that holds them is refused. Placements aren't changed "
        "here. The card shows who each ad set reaches before and after, with Meta's audience "
        "estimates; Meta checks every change before any is made, and each result reports "
        "the targeting Meta shows after the change."
    ),
    provider="meta_ads",
    label="Update Meta Ad Set Targeting",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=MetaAdsUpdateTargetingOutput,
    integration_binding=META_ADS_WRITE_BINDING,
    availability_check=meta_ads_available,
    approval_display_args=_approval_display_args,
    # Edited entries are checked whole, and again by the tool before anything is sent.
    approval_input_model=MetaAdsUpdateTargetingRequest,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Updating Meta Ad Set Targeting",
        completed_label="Updated Meta Ad Set Targeting",
        failed_label="Couldn't Update Meta Ad Set Targeting",
        approval_title="Change Meta Ad Set Targeting",
        approval_prompt="The agent wants to change who these Meta ad sets reach.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Targeting Changes",
                editable=True,
                format="structured",
                # The card adds and excludes places and audiences from searches.
                entity_kinds=("meta_ads_targeting_location", "meta_ads_audience"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
