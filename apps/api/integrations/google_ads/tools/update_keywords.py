# apps/api/integrations/google_ads/tools/update_keywords.py

"""Approval-only tool that changes the bids, URLs, and match types of Google Ads keywords."""

from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext, ToolReturn

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
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets

from ..client import GoogleAdsClient
from ..operations.edits import (
    CriterionChange,
    Edit,
    EditResult,
    FieldChange,
    prepare_edits,
)
from ..operations.keyword_settings import (
    CAMPAIGN_BIDDING_GUARDS,
    CARRIED_SETTINGS,
    SETTING_PATHS,
    KeywordSetting,
    LiveKeyword,
    api_value,
    card_settings,
    read_keyword_settings,
)
from ..operations.mutation_outcomes import GoogleAdsMutationParent
from ..operations.read_search_terms import keyword_key, read_ad_group_keywords
from .schemas.keyword_updates import (
    MAX_KEYWORD_UPDATES,
    GoogleAdsKeywordUpdate,
    GoogleAdsUpdateKeywordsOutput,
    GoogleAdsUpdateKeywordsRequest,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entries
from .utils.ad_group_builds import strategy_name
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client_for_principal
from .utils.edit_runs import EditPlan, run_approved_edits
from .utils.keyword_problems import keyword_bid_not_used, keyword_exists
from .utils.mutation_evidence import (
    google_ads_account_target,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_keywords"
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}
# Every keyword with its settings before, requested, and after, for the most a call can carry.
_MAX_PUBLIC_RESULT_CHARS = 4_000_000
_MAX_MODEL_OUTCOMES = 50

_MISSING = "This keyword no longer exists in Google Ads."
_REMOVED = "This keyword has been removed, so its settings can't change."
_AD_GROUP_REMOVED = "This keyword's ad group has been removed, so its settings can't change."
_CAMPAIGN_REMOVED = "This keyword's campaign has been removed, so its settings can't change."


def _plain_edit(change: GoogleAdsKeywordUpdate) -> FieldChange:
    """Changes the keyword in place; a match type equal to the live one is never sent."""
    bids = "cpc_bid" in change.requested
    return FieldChange(
        resource="adGroupCriterion",
        resource_name=change.resource_name,
        requested={
            SETTING_PATHS[setting]: api_value(setting, value)
            for setting, value in change.requested.items()
        },
        compared=CAMPAIGN_BIDDING_GUARDS if bids else (),
    )


def _replaces(change: GoogleAdsKeywordUpdate, values: Mapping[str, Any]) -> bool:
    match_type = change.requested.get("match_type")
    return match_type is not None and match_type != values.get(SETTING_PATHS["match_type"])


def _replacement_key(change: GoogleAdsKeywordUpdate, check: Mapping[str, Any]) -> str:
    return keyword_key(
        str(check.get("ad_group") or ""),
        str(check.get("text") or ""),
        change.requested["match_type"],
    )


def _edits(change: GoogleAdsKeywordUpdate, check: Mapping[str, Any]) -> list[Edit]:
    """Compiles one change against the keyword's live values.

    A new match type can't be set on a keyword, so the keyword is paused and the same text
    added with the new match type, taking the old keyword's status and settings with the
    requested ones on top. Both go in one atomic request, so neither happens alone.
    """
    values: Mapping[str, Any] = check["values"]
    if not _replaces(change, values):
        edit = _plain_edit(change)
        return [replace(edit, before=edit.live(values) or {})]
    carried = {**card_settings(values), **change.requested}
    criterion: dict[str, Any] = {
        "adGroup": check["ad_group"],
        "status": values["status"],
        "negative": False,
        "keyword": {"text": check["text"], "matchType": change.requested["match_type"]},
    }
    for setting in CARRIED_SETTINGS:
        if value := api_value(setting, carried[setting]):
            criterion[SETTING_PATHS[setting]] = value
    guards = CAMPAIGN_BIDDING_GUARDS if "cpc_bid" in change.requested else ()
    # The old keyword's settings must still be the ones the new keyword copies.
    pause = FieldChange(
        resource="adGroupCriterion",
        resource_name=change.resource_name,
        requested={"status": "PAUSED"},
        compared=(*(SETTING_PATHS[setting] for setting in SETTING_PATHS), *guards),
        atomic_group=change.resource_name,
    )
    add = CriterionChange(
        resource="adGroupCriterion",
        action="add",
        key=_replacement_key(change, check),
        owner=check["ad_group"],
        criterion=criterion,
        atomic_group=change.resource_name,
    )
    return [replace(pause, before=pause.live(values) or {}), add]


def _keyword_problem(live: LiveKeyword | None) -> str | None:
    if live is None:
        return _MISSING
    if live.status == "REMOVED":
        return _REMOVED
    if live.ad_group_status == "REMOVED":
        return _AD_GROUP_REMOVED
    return _CAMPAIGN_REMOVED if live.campaign_status == "REMOVED" else None


def _setting_problems(
    change: GoogleAdsKeywordUpdate, live: LiveKeyword, existing: Mapping[str, str]
) -> dict[KeywordSetting, str]:
    """Refuses a bid the campaign's strategy ignores, and a match type the ad group already has."""
    problems: dict[KeywordSetting, str] = {}
    bid = change.requested.get("cpc_bid")
    if bid is not None and bid != live.settings()["cpc_bid"] and "cpc_bid" not in live.bids_used:
        problems["cpc_bid"] = keyword_bid_not_used(
            live.campaign_name, strategy_name(live.strategy_type, portfolio=live.portfolio)
        )
    match_type = change.requested.get("match_type")
    if (
        _replaces(change, live.values)
        and keyword_key(live.ad_group, live.text, match_type) in existing
    ):
        problems["match_type"] = keyword_exists(live.text, match_type, live.ad_group_name)
    return problems


async def google_ads_update_keywords(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsKeywordUpdate],
        Field(
            min_length=1,
            max_length=MAX_KEYWORD_UPDATES,
            description="One entry per keyword, with only the settings that change.",
        ),
    ],
) -> ToolReturn[dict[str, Any]]:
    request = validated_request(GoogleAdsUpdateKeywordsRequest, {"changes": changes})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_key = {change.resource_name: change for change in request.changes}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_changes = [
            by_key[
                f"customers/{reference.customer_id}/adGroupCriteria/"
                f"{reference.ad_group_id}~{reference.criterion_id}"
            ]
            for reference in selected
        ]
        planned = {
            change.resource_name: _approved_edits(change, shown.get(change.resource_name))
            for change in account_changes
        }

        async def plan(_client: GoogleAdsClient) -> EditPlan:
            edits = [edit for items in planned.values() for edit in items]
            return edits, _pending_detail(entry, account_changes, planned, shown)

        async def result(client: GoogleAdsClient, applied: EditResult) -> dict[str, Any]:
            return _result(entry, account_changes, planned, shown, applied)

        return await run_approved_edits(
            ctx,
            entry,
            tool_name="google_ads_update_keywords",
            operation=_OPERATION,
            family="keyword_settings",
            plan=plan,
            read=lambda client: _reader(client, entry, account_changes, shown),
            result=result,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.keyword for change in request.changes],
        operation=operation,
    )
    return split_fan_out_tool_return(results)


def _approved_edits(change: GoogleAdsKeywordUpdate, check: Any) -> list[Edit]:
    """Builds the edits against the values the approver saw, so `apply_edits` refuses stale ones.

    The check must be for exactly these settings, and any problem it showed still stands.
    """
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("requested") != change.requested
    ):
        return [replace(_plain_edit(change), refused=NOT_SHOWN)]
    problems = check.get("problems")
    problem = check.get("problem") or next(
        iter(problems.values() if isinstance(problems, Mapping) else ()), None
    )
    if problem or not isinstance(check.get("values"), Mapping):
        return [replace(_plain_edit(change), refused=str(problem or NOT_SHOWN))]
    return _edits(change, check)


def _reader(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsKeywordUpdate],
    shown: Mapping[str, Any],
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    """Reads the keywords, and the keywords bid on where a new match type is added."""
    names = [change.resource_name for change in changes]
    ad_group_ids = sorted(
        {
            change.keyword.ad_group_id
            for change in changes
            if _replaces(change, _shown_values(shown.get(change.resource_name)))
        }
    )

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await read_keyword_settings(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            resource_names=names,
        )
        existing = await read_ad_group_keywords(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            ad_group_ids=ad_group_ids,
        )
        return {
            **{name: item.values for name, item in live.items()},
            **{key: {"resourceName": name} for key, name in existing.items()},
        }

    return read


def _shown_values(check: Any) -> Mapping[str, Any]:
    values = check.get("values") if isinstance(check, Mapping) else None
    return values if isinstance(values, Mapping) else {}


def _text(check: Any, key: str) -> str:
    value = check.get(key) if isinstance(check, Mapping) else None
    return str(value or "")


def _pending_detail(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsKeywordUpdate],
    planned: Mapping[str, Sequence[Edit]],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    """Records which settings change on each keyword; URL values stay out of the audit record."""
    updates: list[IntegrationOperationIntent] = []
    replacements: list[IntegrationOperationIntent] = []
    for change in changes:
        check = shown.get(change.resource_name)
        text = _text(check, "text") or change.keyword.label
        for edit in planned[change.resource_name]:
            if isinstance(edit, CriterionChange):
                replacements.append(
                    IntegrationOperationIntent(
                        fields={
                            "object": edit.key,
                            "text": text,
                            "match_type": str(change.requested["match_type"]),
                            "replaces": change.resource_name,
                        }
                    )
                )
            else:
                updates.append(
                    IntegrationOperationIntent(
                        fields={
                            "object": edit.key,
                            "text": text,
                            "settings": ",".join(change.requested),
                        }
                    )
                )
    groups = [
        IntegrationOperationIntentGroup(
            key="keyword:update-settings",
            action="update_settings",
            entity_type="google_ads_keyword",
            items=updates,
        )
    ]
    if replacements:
        groups.append(
            IntegrationOperationIntentGroup(
                key="keyword:replace-match-type",
                action="create",
                entity_type="google_ads_keyword",
                items=replacements,
            )
        )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry), intent_groups=groups
    )


def _state(parent: GoogleAdsMutationParent) -> str:
    if parent.decision == "skipped":
        return "already_set"
    effect = parent.effects[0] if parent.effects else None
    return _OUTCOMES[effect.outcome if effect else "unverified"]


def _combined(states: Sequence[str]) -> str:
    for state in ("failed", "unverified", "updated"):
        if state in states:
            return state
    return "already_set"


def _keyword_result(
    change: GoogleAdsKeywordUpdate,
    edits: Sequence[Edit],
    check: Any,
    parents: Mapping[str, GoogleAdsMutationParent],
    result: EditResult,
) -> dict[str, Any]:
    items = [parents[edit.key] for edit in edits]
    outcome = _combined([_state(parent) for parent in items])
    effect = next(
        (
            effect
            for parent in items
            for effect in parent.effects
            if effect.outcome in {"failed", "unverified"}
        ),
        None,
    )
    current = check.get("current") if isinstance(check, Mapping) else None
    current = current if isinstance(current, Mapping) else {}
    added = next((edit for edit in edits if isinstance(edit, CriterionChange)), None)
    if added is not None:
        # The new keyword holds the requested settings once Google confirms it exists.
        add_parent = parents[added.key]
        confirmed = _state(add_parent) == "updated"
        replacement = next(iter(add_parent.effects)).external_ref if confirmed else None
        after = {**current, **change.requested} if confirmed else dict(current)
        read_back = confirmed
    else:
        replacement = None
        values = result.after.get(change.resource_name)
        skipped = items[0].decision == "skipped"
        after = dict(current) if skipped else card_settings(values) if values is not None else {}
        read_back = skipped or values is not None
    return {
        "resource_name": change.resource_name,
        "text": _text(check, "text") or change.keyword.text,
        "match_type": _text(check, "match_type") or change.keyword.match_type,
        "ad_group_name": _text(check, "ad_group_name"),
        "campaign_name": _text(check, "campaign_name"),
        "replacement": replacement,
        "read_back": read_back,
        "outcome": outcome,
        "settings": [
            {
                "setting": setting,
                "before": current.get(setting),
                "requested": requested,
                "after": after.get(setting),
                "outcome": "already_set" if current.get(setting) == requested else outcome,
            }
            for setting, requested in change.requested.items()
        ],
        "error_code": effect.error_code if effect is not None else None,
        "message": effect.message if effect is not None else None,
    }


def _result(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsKeywordUpdate],
    planned: Mapping[str, Sequence[Edit]],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    """Returns every keyword for the card, and the counts with what didn't change for the agent."""
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    keywords = [
        _keyword_result(
            change, planned[change.resource_name], shown.get(change.resource_name), parents, result
        )
        for change in changes
    ]
    outcomes = Counter(keyword["outcome"] for keyword in keywords)
    missed = [keyword for keyword in keywords if keyword["outcome"] in {"failed", "unverified"}]
    base = {
        "account_id": entry.external_id,
        "currency": account_facts(entry).currency,
        "counts": {
            key: outcomes.get(key, 0) for key in ("updated", "already_set", "failed", "unverified")
        },
    }
    return {
        "display_result": {**base, "keywords": keywords, "keywords_truncated": False},
        "model_result": {
            **base,
            "keywords": missed[:_MAX_MODEL_OUTCOMES],
            "keywords_truncated": len(missed) > _MAX_MODEL_OUTCOMES,
        },
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per keyword, its live settings and Google's dry run."""
    request = GoogleAdsUpdateKeywordsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsKeywordUpdate]] = defaultdict(list)
    for change in request.changes:
        by_account[change.keyword.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, changes in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), changes))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    changes: Sequence[GoogleAdsKeywordUpdate],
) -> dict[str, dict[str, Any]]:
    """Reads one account's keywords and dry runs the changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        login = login_customer_id(entry)
        live = await read_keyword_settings(
            client,
            customer_id=entry.external_id,
            login_customer_id=login,
            resource_names=[change.resource_name for change in changes],
        )
        replacing = sorted(
            {
                item.ad_group.rsplit("/", 1)[-1]
                for change in changes
                if (item := live.get(change.resource_name)) and _replaces(change, item.values)
            }
        )
        existing = dict(
            await read_ad_group_keywords(
                client,
                customer_id=entry.external_id,
                login_customer_id=login,
                ad_group_ids=replacing,
            )
        )
        checks: dict[str, dict[str, Any]] = {}
        for change in changes:
            item = live.get(change.resource_name)
            check = checks[change.resource_name] = _check(change, item, existing)
            # A later change that would add the same keyword is refused as already there.
            if item and _replaces(change, item.values) and not check["problems"]:
                existing[_replacement_key(change, check)] = change.resource_name
        rejected = await _dry_run(client, entry, changes, checks)
    except (IntegrationError, LookupError):
        return {change.resource_name: {"unavailable": True} for change in changes}
    for name, problem in rejected.items():
        checks[name]["problem"] = problem
    return checks


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsKeywordUpdate],
    checks: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Returns Google's rejection per keyword, asking only about keywords with no problem yet."""
    owners: dict[str, str] = {}
    edits: list[Edit] = []
    for change in changes:
        check = checks[change.resource_name]
        if check["problem"] or check["problems"]:
            continue
        for edit in _edits(change, check):
            owners[edit.key] = change.resource_name
            edits.append(edit)
    if not edits:
        return {}
    values = {edit.key: edit.before for edit in edits if isinstance(edit, FieldChange)}

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return values

    prepared = await prepare_edits(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        edits=edits,
        read=read,
        operation=_OPERATION,
    )
    rejected: dict[str, str] = {}
    for edit in prepared:
        if edit.refused:
            rejected.setdefault(owners[edit.key], f"Google says: {edit.refused}")
    return rejected


def _check(
    change: GoogleAdsKeywordUpdate, live: LiveKeyword | None, existing: Mapping[str, str]
) -> dict[str, Any]:
    """Builds the card's view of one keyword, and the live values approval plans against."""
    if live is None:
        return {
            "unavailable": False,
            "text": change.keyword.text,
            "match_type": change.keyword.match_type,
            "requested": change.requested,
            "current": {},
            "problem": _MISSING,
            "problems": {},
        }
    return {
        "unavailable": False,
        "text": live.text,
        "match_type": live.values.get(SETTING_PATHS["match_type"]),
        "status": live.status,
        "ad_group": live.ad_group,
        "ad_group_name": live.ad_group_name,
        "campaign_name": live.campaign_name,
        # The campaign's strategy, and whether it uses keyword bids, so the card can explain.
        "strategy_name": strategy_name(live.strategy_type, portfolio=live.portfolio),
        "bids_used": sorted(live.bids_used),
        "current": live.settings(),
        "requested": change.requested,
        # What approval plans against, in Google's terms.
        "values": dict(live.values),
        "problem": _keyword_problem(live),
        "problems": _setting_problems(change, live, existing),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_keywords",
    function=google_ads_update_keywords,
    description=(
        "Change the bids, URLs, and match types of existing Google Ads keywords, up to 500 "
        "keywords per call, in one approval. Each entry names one keyword (a google_ads_keyword "
        "reference) and only the settings that change: cpc_bid, the keyword's max CPC in the "
        "account currency, which Google uses only when the campaign uses Manual CPC, or "
        '"none" to use the ad group\'s bid; final_urls and final_mobile_urls, replacing the '
        "keyword's lists (an empty list clears them); url_options with final_url_suffix, "
        "tracking_template, and custom_parameters (up to 8 key and value pairs), where an "
        "empty value clears it; and match_type (EXACT, PHRASE, or BROAD). Google can't change "
        "a keyword's match type, so a new match type pauses the keyword and adds the same "
        "text with the new match type, its status, and its settings, in one request where "
        "both happen or neither does. To pause or enable keywords use google_ads_update_status, "
        "and to remove them use google_ads_remove_objects. Each result reports what Google Ads "
        "shows after the change."
    ),
    provider="google_ads",
    label="Update Google Ads Keywords",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=180,
    output_model=GoogleAdsUpdateKeywordsOutput,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateKeywordsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Keywords",
        completed_label="Updated Google Ads Keywords",
        failed_label="Couldn't Update Google Ads Keywords",
        approval_title="Update Keywords",
        approval_prompt="The agent wants to change these Google Ads keywords.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Keyword Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_keyword",),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
