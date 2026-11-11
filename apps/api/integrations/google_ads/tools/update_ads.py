# apps/api/integrations/google_ads/tools/update_ads.py

"""Approval-only tool that edits the headlines, descriptions, paths, and final URLs of responsive search ads."""

import contextlib
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
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
from ..operations.edits import Edit, EditResult, FieldChange, prepare_edits
from ..operations.responsive_search_ad_edits import (
    DESCRIPTIONS_PATH,
    FINAL_URLS_PATH,
    HEADLINES_PATH,
    PATH_PATHS,
    RESPONSIVE_SEARCH_AD,
    AdCopy,
    LiveAd,
    api_values,
    card_copy,
    merged_copy,
    read_responsive_search_ads,
)
from ..operations.responsive_search_ads import AdReview, read_ad_reviews
from .schemas.ad_updates import (
    MAX_AD_UPDATES,
    GoogleAdsAdUpdate,
    GoogleAdsUpdateAdsOutput,
    GoogleAdsUpdateAdsRequest,
)
from .utils.accounts import NOT_SHOWN, approval_accounts, writable_entries
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client_for_principal
from .utils.edit_runs import EditPlan, run_approved_edits
from .utils.mutation_evidence import (
    google_ads_account_target,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_ads"
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}

_MISSING = "This ad no longer exists in Google Ads."
_REMOVED = "This ad has been removed, so it can't change."
_NOT_RESPONSIVE = "Only responsive search ads can be edited here."


# The copy a refused edit is built against, so its settings still name what it would send.
_NO_COPY: AdCopy = {
    "headlines": [],
    "descriptions": [],
    "path1": None,
    "path2": None,
    "final_url": None,
}


def _ad_key(change: GoogleAdsAdUpdate) -> str:
    """The `Ad` resource the edit updates, which `AdService` names without the ad group."""
    return f"customers/{change.ad.customer_id}/ads/{change.ad.ad_id}"


def _edit(change: GoogleAdsAdUpdate, current: AdCopy) -> FieldChange:
    """Sends the merged headlines and descriptions whole, plus the links the entry names."""
    after, _problems = merged_copy(current, change.requested)
    values = api_values(after)
    paths = [HEADLINES_PATH, DESCRIPTIONS_PATH]
    paths += [path for key, path in PATH_PATHS.items() if key in change.requested]
    if "final_url" in change.requested:
        paths.append(FINAL_URLS_PATH)
    return FieldChange(
        resource="ad",
        resource_name=_ad_key(change),
        requested={path: values[path] for path in paths},
    )


def _ad_problem(live: LiveAd | None) -> str | None:
    if live is None:
        return _MISSING
    if live.status == "REMOVED":
        return _REMOVED
    return _NOT_RESPONSIVE if live.type != RESPONSIVE_SEARCH_AD else None


async def google_ads_update_ads(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsAdUpdate],
        Field(
            min_length=1,
            max_length=MAX_AD_UPDATES,
            description="One entry per ad, with only the edits to make to it.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateAdsRequest, {"changes": changes})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_key = {(change.ad.customer_id, change.ad.ad_id): change for change in request.changes}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_changes = [by_key[reference.customer_id, reference.ad_id] for reference in selected]

        async def plan(_client: GoogleAdsClient) -> EditPlan:
            edits = [
                _approved_edit(change, shown.get(change.ad.resource_name))
                for change in account_changes
            ]
            return edits, _pending_detail(entry, account_changes, shown)

        async def result(client: GoogleAdsClient, applied: EditResult) -> dict[str, Any]:
            reviews = await _reviews(client, entry, account_changes, applied)
            return _result(entry, account_changes, shown, applied, reviews)

        return await run_approved_edits(
            ctx,
            entry,
            tool_name="google_ads_update_ads",
            operation=_OPERATION,
            family="ads",
            plan=plan,
            read=lambda client: _reader(client, entry, account_changes),
            result=result,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.ad for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _approved_edit(change: GoogleAdsAdUpdate, check: Any) -> FieldChange:
    """Builds the edit against the ad the approver saw, so `apply_edits` refuses a changed one.

    The check must be for exactly these edits, and any problem it showed still stands.
    """
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("requested") != change.requested
    ):
        return replace(_edit(change, _NO_COPY), refused=NOT_SHOWN)
    current = check.get("current")
    problems = check.get("problems")
    problem = check.get("problem") or next(
        iter(problems if isinstance(problems, list) else ()), None
    )
    if not isinstance(current, Mapping):
        return replace(_edit(change, _NO_COPY), refused=str(problem or NOT_SHOWN))
    edit = _edit(change, current)
    if problem:
        return replace(edit, refused=str(problem))
    values = check.get("values")
    return replace(edit, before=values if isinstance(values, Mapping) else {})


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, changes: Sequence[GoogleAdsAdUpdate]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    keys = {change.ad.resource_name: _ad_key(change) for change in changes}

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await read_responsive_search_ads(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            resource_names=list(keys),
        )
        return {keys[name]: ad.values for name, ad in live.items()}

    return read


async def _reviews(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsAdUpdate],
    result: EditResult,
) -> dict[str, AdReview]:
    """Reads Google's policy review for the ads that changed; a failed read leaves it out."""
    changed = [change.ad.resource_name for change in changes if _ad_key(change) in result.after]
    if not changed:
        return {}
    with contextlib.suppress(IntegrationError):
        return await read_ad_reviews(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            resource_names=changed,
        )
    return {}


def _text(check: Any, key: str) -> str:
    value = check.get(key) if isinstance(check, Mapping) else None
    return str(value or "")


def _name(change: GoogleAdsAdUpdate, check: Any) -> str:
    return _text(check, "name") or change.ad.label


def _pending_detail(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsAdUpdate],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    """Records which edits each ad gets; the copy itself stays out of the audit record."""
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="ad:update-copy",
                action="update_copy",
                entity_type="google_ads_ad",
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "object": _ad_key(change),
                            "name": _name(change, shown.get(change.ad.resource_name)),
                            "settings": ",".join(change.requested),
                        }
                    )
                    for change in changes
                ],
            )
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsAdUpdate],
    shown: Mapping[str, Any],
    result: EditResult,
    reviews: Mapping[str, AdReview],
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    ads = []
    for change in changes:
        key = _ad_key(change)
        check = shown.get(change.ad.resource_name)
        current = check.get("current") if isinstance(check, Mapping) else None
        parent = parents[key]
        effect = parent.effects[0] if parent.effects else None
        skipped = parent.decision == "skipped"
        after = result.after.get(key)
        review = reviews.get(change.ad.resource_name)
        ads.append(
            {
                "resource_name": change.ad.resource_name,
                "ad_id": change.ad.ad_id,
                "name": _name(change, check),
                "ad_group_name": _text(check, "ad_group_name"),
                "campaign_name": _text(check, "campaign_name"),
                "before": current if isinstance(current, Mapping) else None,
                "requested": (
                    merged_copy(current, change.requested)[0]
                    if isinstance(current, Mapping)
                    else None
                ),
                "after": card_copy(after) if after is not None else None,
                "outcome": (
                    "already_set"
                    if skipped
                    else _OUTCOMES[effect.outcome if effect else "unverified"]
                ),
                "review_status": review.review_status if review else None,
                "approval_status": review.approval_status if review else None,
                "error_code": effect.error_code if effect is not None else None,
                "message": effect.message if effect is not None else None,
            }
        )
    return {"account_id": entry.external_id, "ads": ads}


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per ad, its live copy, the merged copy, and Google's dry run."""
    request = GoogleAdsUpdateAdsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsAdUpdate]] = defaultdict(list)
    for change in request.changes:
        by_account[change.ad.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, changes in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), changes))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    changes: Sequence[GoogleAdsAdUpdate],
) -> dict[str, dict[str, Any]]:
    """Reads one account's ads and dry runs the edits; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await read_responsive_search_ads(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            resource_names=[change.ad.resource_name for change in changes],
        )
        rejected = await _dry_run(client, entry, changes, live)
    except (IntegrationError, LookupError):
        return {change.ad.resource_name: {"unavailable": True} for change in changes}
    return {
        change.ad.resource_name: _check(
            change, live.get(change.ad.resource_name), rejected.get(_ad_key(change))
        )
        for change in changes
    }


def _checkable(change: GoogleAdsAdUpdate, live: LiveAd | None) -> bool:
    return (
        live is not None
        and _ad_problem(live) is None
        and not merged_copy(live.copy(), change.requested)[1]
    )


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsAdUpdate],
    live: Mapping[str, LiveAd],
) -> dict[str, str]:
    """Returns Google's rejection per ad, asking only about ads with no problem yet."""
    checked = {
        _ad_key(change): live[change.ad.resource_name]
        for change in changes
        if _checkable(change, live.get(change.ad.resource_name))
    }
    edits = [
        _edit(change, checked[_ad_key(change)].copy())
        for change in changes
        if _ad_key(change) in checked
    ]
    if not edits:
        return {}

    async def read(items: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return {item.key: checked[item.key].values for item in items}

    prepared = await prepare_edits(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        edits=edits,
        read=read,
        operation=_OPERATION,
    )
    return {edit.key: f"Google says: {edit.refused}" for edit in prepared if edit.refused}


def _check(change: GoogleAdsAdUpdate, live: LiveAd | None, rejected: str | None) -> dict[str, Any]:
    """Builds the card's view of one ad, and the live values approval plans against."""
    current = live.copy() if live is not None else None
    after, problems = merged_copy(current, change.requested) if current else (None, [])
    return {
        "unavailable": False,
        "name": live.name if live else change.ad.label,
        "ad_group_name": live.ad_group_name if live else None,
        "campaign_name": live.campaign_name if live else None,
        "status": live.status if live else None,
        "approval_status": live.approval_status if live else None,
        "current": current,
        "requested": change.requested,
        "after": after,
        # What approval plans against, in Google's terms, for the paths the edit sends.
        "values": (_edit(change, current).live(live.values) or {}) if live and current else {},
        "problem": _ad_problem(live) or rejected,
        "problems": problems if _ad_problem(live) is None else [],
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_ads",
    function=google_ads_update_ads,
    description=(
        "Edit the copy and links of existing Google Ads responsive search ads, up to 50 ads per "
        "call, in one approval. Each entry names one ad (a google_ads_ad reference) and only "
        "the edits to make: add_headlines (text up to 30 characters, optional pin HEADLINE_1 to "
        "HEADLINE_3); remove_headlines (the exact text of headlines to remove); "
        "add_descriptions (text up to 90 characters, optional pin DESCRIPTION_1 or "
        "DESCRIPTION_2); remove_descriptions; pins, each a text already in the ad (or added "
        "here) with a pin, or null to unpin; path1 and path2 (up to 15 characters, empty to "
        "clear); and final_url. An added headline or description takes the place of a removed "
        "one, in order, so to replace a headline remove it and add the new one, giving the new "
        "one any pin it needs. After the edits an ad must have 3 to 15 different headlines and "
        "2 to 4 different descriptions. Read the ads' current copy first with "
        "google_ads_run_report, selecting ad_group_ad.ad.responsive_search_ad.headlines and "
        "descriptions. Edited ads go back through Google's policy review. Status and "
        "removal aren't supported here. Each result reports what Google Ads shows after the "
        "change and its review status."
    ),
    provider="google_ads",
    label="Update Google Ads Ads",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsUpdateAdsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateAdsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Ads",
        completed_label="Updated Google Ads Ads",
        failed_label="Couldn't Update Google Ads Ads",
        approval_title="Change Ads",
        approval_prompt="The agent wants to change the copy of these Google Ads ads.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Ad Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_ad",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
