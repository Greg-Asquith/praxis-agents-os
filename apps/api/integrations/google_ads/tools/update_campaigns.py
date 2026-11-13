# apps/api/integrations/google_ads/tools/update_campaigns.py

"""Approval-only tool that changes the settings, conversion goals, and bidding of Google Ads campaigns."""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
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
from ..operations.asset_automation import AUTOMATION_SWITCHES, with_automation_changes
from ..operations.campaign_bidding import (
    BIDDING_GUARDS,
    AdGroupBids,
    Bidding,
    bidding_notes,
    bidding_paths,
    changes_strategy,
    needs_conversions,
    read_ad_group_bids,
    read_conversions,
    resolved_bidding,
    strategy_problem,
)
from ..operations.campaign_goals import (
    NO_GOALS_PROBLEM,
    LiveCampaignGoals,
    goals_from_values,
    level_edit,
    read_campaign_goals,
)
from ..operations.campaign_settings import (
    AUTOMATION_PATH,
    SETTING_PATHS,
    CampaignSetting,
    LiveCampaignSettings,
    api_value,
    card_settings,
    read_campaign_settings,
)
from ..operations.edits import Edit, EditResult, FieldChange, prepare_edits
from ..operations.list_bidding_strategies import (
    MAX_BIDDING_STRATEGY_LOOKUP,
    list_bidding_strategies,
)
from .schemas.campaign_updates import (
    MAX_CAMPAIGN_UPDATES,
    GoogleAdsCampaignUpdate,
    GoogleAdsUpdateCampaignsOutput,
    GoogleAdsUpdateCampaignsRequest,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entries
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client_for_principal
from .utils.edit_runs import EditPlan, run_approved_edits
from .utils.mutation_evidence import (
    google_ads_account_target,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_campaigns"
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}
# The channels on which each setting can change. Search campaigns always show on Google Search.
_SETTING_CHANNELS: dict[CampaignSetting, frozenset[str]] = {
    "search_partners": frozenset({"SEARCH", "SHOPPING"}),
    "display_expansion": frozenset({"SEARCH"}),
    "video_pages": frozenset({"PERFORMANCE_MAX"}),
    "final_url_expansion": frozenset({"PERFORMANCE_MAX"}),
    "text_customisation": frozenset({"PERFORMANCE_MAX"}),
}
# The settings held in the campaign's one automation list.
_AUTOMATION = frozenset({"video_pages", *AUTOMATION_SWITCHES})

_MISSING = "This campaign no longer exists in Google Ads."
_REMOVED = "This campaign has been removed, so its settings can't change."
_STARTED = "This campaign has already started, so Google Ads won't change its start date."
_START_PAST = "Choose a start date after today."
_END_PAST = "Choose an end date of today or later."
_END_BEFORE_START = "The end date must be on or after the start date ({start})."
_WRONG_CHANNEL = {
    "search_partners": "Search Partners can only change on Search and Shopping campaigns.",
    "display_expansion": "Display expansion can only change on Search campaigns.",
    "video_pages": "Google only finds videos on pages for Performance Max campaigns.",
    "final_url_expansion": "Final URL expansion can only change on Performance Max campaigns.",
    "text_customisation": "Text customisation can only change on Performance Max campaigns.",
}
_TEXT_WITH_EXPANSION = (
    "Google customises text whenever final URL expansion is on. Turn off final URL expansion too."
)
_EXPANSION_NEEDS_TEXT = (
    "Final URL expansion needs text customisation. Turn on text customisation too."
)
_PORTFOLIO_MISSING = "This portfolio strategy no longer exists in Google Ads."

# Each portfolio strategy's name and Google type, by resource name.
type Portfolios = Mapping[str, Mapping[str, str]]


def _bidding(
    change: GoogleAdsCampaignUpdate, current: Mapping[str, Any]
) -> tuple[Bidding | None, str | None]:
    """The strategy a bidding request leaves the campaign on, and why it can't, if so."""
    requested = change.requested.get("bidding")
    if requested is None:
        return None, None
    live = current.get("bidding")
    return resolved_bidding(requested, live if isinstance(live, Mapping) else {})


def _effective(
    change: GoogleAdsCampaignUpdate, current: Mapping[str, Any]
) -> dict[CampaignSetting, Any]:
    """The requested settings in card terms, with a targets-only bidding request resolved."""
    values = dict(change.requested)
    bidding, problem = _bidding(change, current)
    if bidding is not None and problem is None:
        values["bidding"] = bidding
    return values


def _campaign_edit(
    change: GoogleAdsCampaignUpdate, current: Mapping[str, Any], values: Mapping[str, Any]
) -> FieldChange:
    """Builds the edit to the campaign's own fields against its live settings.

    Args:
        current: The settings in card terms, which bidding paths need.
        values: The settings as Google stores them, by path. The automation settings are
            entries of one list, which Google replaces whole.
    """
    requested = {
        SETTING_PATHS[setting]: api_value(setting, value)
        for setting, value in change.requested.items()
        if setting in SETTING_PATHS and setting not in _AUTOMATION
    }
    automation = {s: value for s, value in change.requested.items() if s in _AUTOMATION}
    if automation:
        requested[AUTOMATION_PATH] = with_automation_changes(
            values.get(AUTOMATION_PATH), automation
        )
    bidding, problem = _bidding(change, current)
    if bidding is not None and problem is None:
        requested.update(bidding_paths(bidding, current.get("bidding") or {}))
    return FieldChange(
        resource="campaign",
        resource_name=change.resource_name,
        requested=requested,
        compared=BIDDING_GUARDS if bidding is not None else (),
    )


def _edits(
    change: GoogleAdsCampaignUpdate,
    current: Mapping[str, Any],
    values: Mapping[str, Any],
    goals: LiveCampaignGoals | None,
) -> list[FieldChange]:
    """Builds the change's edits: the campaign's own fields, then each of its goals.

    Without the live goals only the goal level edit is built, which is enough to carry a refusal.
    """
    edits = []
    if change.requested.keys() - {"conversion_goals"}:
        edits.append(_campaign_edit(change, current, values))
    if "conversion_goals" in change.requested:
        requested = change.requested["conversion_goals"]
        reference = change.campaign
        edits.extend(
            goals.edits(requested)
            if goals is not None
            else [level_edit(reference.customer_id, reference.campaign_id, requested)]
        )
    return edits


def _current(
    live: LiveCampaignSettings, goals: LiveCampaignGoals | None
) -> dict[CampaignSetting, Any]:
    """Every setting in card terms; conversion goals are left out when Google returned none."""
    current = live.settings()
    if goals is not None:
        current["conversion_goals"] = goals.card()
    return current


def _bidding_problem(
    change: GoogleAdsCampaignUpdate, live: LiveCampaignSettings, portfolios: Portfolios
) -> str | None:
    current = live.settings()
    bidding, problem = _bidding(change, current)
    if bidding is None or problem is not None or bidding == current["bidding"]:
        return problem
    if bidding.get("strategy") == "PORTFOLIO" and bidding.get("portfolio") not in portfolios:
        return _PORTFOLIO_MISSING
    return strategy_problem(bidding, live.channel)


def _setting_problems(
    change: GoogleAdsCampaignUpdate,
    live: LiveCampaignSettings,
    goals: LiveCampaignGoals | None,
    today: date,
    portfolios: Portfolios,
) -> dict[CampaignSetting, str]:
    """Google's rules for the settings that change, checked before Google is asked."""
    current = _current(live, goals)
    requested = _effective(change, current)
    changing = {s: v for s, v in requested.items() if v != current.get(s)}
    problems = _date_problems(requested, current, changing, today.isoformat())
    problems.update(_automation_problems(requested, current, changing))
    for limited, channels in _SETTING_CHANNELS.items():
        # Asked of every request, because a live value only means something on these channels.
        if limited in requested and live.channel not in channels:
            problems[limited] = _WRONG_CHANNEL[limited]
    if "conversion_goals" in changing:
        problem = (
            goals.problem(changing["conversion_goals"]) if goals is not None else NO_GOALS_PROBLEM
        )
        if problem:
            problems["conversion_goals"] = problem
    if bidding := _bidding_problem(change, live, portfolios):
        problems["bidding"] = bidding
    return problems


def _date_problems(
    requested: Mapping[CampaignSetting, Any],
    current: Mapping[CampaignSetting, Any],
    changing: Mapping[CampaignSetting, Any],
    now: str,
) -> dict[CampaignSetting, str]:
    problems: dict[CampaignSetting, str] = {}
    live_start = current["start_date"]
    if "start_date" in changing:
        if live_start is not None and live_start <= now:
            problems["start_date"] = _STARTED
        elif changing["start_date"] <= now:
            problems["start_date"] = _START_PAST
    if "end_date" in changing and changing["end_date"] is not None and changing["end_date"] < now:
        problems["end_date"] = _END_PAST
    start = requested.get("start_date", live_start)
    end = requested["end_date"] if "end_date" in requested else current["end_date"]
    if start and end and end < start and not problems:
        setting: CampaignSetting = "end_date" if "end_date" in changing else "start_date"
        if setting in changing:
            problems[setting] = _END_BEFORE_START.format(start=start)
    return problems


def _automation_problems(
    requested: Mapping[CampaignSetting, Any],
    current: Mapping[CampaignSetting, Any],
    changing: Mapping[CampaignSetting, Any],
) -> dict[CampaignSetting, str]:
    """Google keeps text customisation on for as long as final URL expansion is on."""
    expansion = requested.get("final_url_expansion", current["final_url_expansion"])
    text = requested.get("text_customisation", current["text_customisation"])
    if not expansion or text:
        return {}
    if "text_customisation" in changing:
        return {"text_customisation": _TEXT_WITH_EXPANSION}
    if "final_url_expansion" in changing:
        return {"final_url_expansion": _EXPANSION_NEEDS_TEXT}
    return {}


def _campaign_problem(live: LiveCampaignSettings | None) -> str | None:
    if live is None:
        return _MISSING
    return _REMOVED if live.status == "REMOVED" else None


async def google_ads_update_campaigns(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsCampaignUpdate],
        Field(
            min_length=1,
            max_length=MAX_CAMPAIGN_UPDATES,
            description="One entry per campaign, with only the settings that change.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateCampaignsRequest, {"changes": changes})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}
    by_key = {
        (change.campaign.customer_id, change.campaign.campaign_id): change
        for change in request.changes
    }

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        account_changes = [
            by_key[reference.customer_id, reference.campaign_id] for reference in selected
        ]

        async def plan(_client: GoogleAdsClient) -> EditPlan:
            planned = [
                (change, _approved_edits(change, shown.get(change.resource_name)))
                for change in account_changes
            ]
            edits = [edit for _change, change_edits in planned for edit in change_edits]
            return edits, _pending_detail(entry, planned, shown)

        async def result(client: GoogleAdsClient, applied: EditResult) -> dict[str, Any]:
            return _result(entry, account_changes, shown, applied)

        return await run_approved_edits(
            ctx,
            entry,
            tool_name="google_ads_update_campaigns",
            operation=_OPERATION,
            family="campaign_settings",
            plan=plan,
            read=lambda client: _reader(client, entry, account_changes),
            result=result,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.campaign for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _approved_edits(change: GoogleAdsCampaignUpdate, check: Any) -> list[FieldChange]:
    """Builds the edits against the values the approver saw, so `apply_edits` refuses stale ones.

    The check must be for exactly these settings, and any problem it showed still stands.
    """
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("requested") != change.requested
        or not isinstance(check.get("current"), Mapping)
    ):
        return [replace(edit, refused=NOT_SHOWN) for edit in _edits(change, {}, {}, None)]
    values = check.get("values")
    goal_values = check.get("goal_values")
    live: dict[str, Any] = {
        **(goal_values if isinstance(goal_values, Mapping) else {}),
        change.resource_name: values if isinstance(values, Mapping) else {},
    }
    reference = change.campaign
    goals = goals_from_values(reference.customer_id, reference.campaign_id, live)
    edits = _edits(change, check["current"], live[change.resource_name], goals)
    problems = check.get("problems")
    problem = check.get("problem") or next(
        iter(problems.values() if isinstance(problems, Mapping) else ()), None
    )
    if problem:
        return [replace(edit, refused=str(problem)) for edit in edits]
    return [replace(edit, before=edit.live(live.get(edit.key)) or {}) for edit in edits]


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, changes: Sequence[GoogleAdsCampaignUpdate]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    campaign_ids = [change.campaign.campaign_id for change in changes]
    goal_ids = [
        change.campaign.campaign_id for change in changes if "conversion_goals" in change.requested
    ]

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        account = {"customer_id": entry.external_id, "login_customer_id": login_customer_id(entry)}
        live = await read_campaign_settings(client, **account, campaign_ids=campaign_ids)
        values: dict[str, Mapping[str, Any]] = {name: item.values for name, item in live.items()}
        if goal_ids:
            goals = await read_campaign_goals(client, **account, campaign_ids=goal_ids)
            for item in goals.values():
                values.update(item.values())
        return values

    return read


def _name(change: GoogleAdsCampaignUpdate, check: Any) -> str:
    shown_name = check.get("name") if isinstance(check, Mapping) else None
    return str(shown_name or change.campaign.label)


def _pending_detail(
    entry: ResolvedContextEntry,
    planned: Sequence[tuple[GoogleAdsCampaignUpdate, Sequence[FieldChange]]],
    shown: Mapping[str, Any],
) -> PendingIntegrationOperationDetail:
    """Records which settings change on each campaign; URL values stay out of the audit record.

    A campaign's goals are objects of their own, so each one that the change sets is recorded.
    """
    campaigns, goals = [], []
    for change, edits in planned:
        name = _name(change, shown.get(change.resource_name))
        for edit in edits:
            own = edit.key == change.resource_name
            settings = ",".join(s for s in change.requested if s != "conversion_goals")
            fields = {
                "object": edit.key,
                "name": name,
                "settings": settings if own else "conversion_goals",
            }
            (campaigns if own else goals).append(IntegrationOperationIntent(fields=fields))
    groups = [
        IntegrationOperationIntentGroup(
            key=key, action="update_settings", entity_type=entity_type, items=items
        )
        for key, entity_type, items in (
            ("campaign:update-settings", "google_ads_campaign", campaigns),
            ("campaign_goal:update-settings", "google_ads_campaign_goal", goals),
        )
        if items
    ]
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry), intent_groups=groups
    )


def _outcome(parents: Sequence[Any]) -> tuple[str, Any]:
    """The outcome of the edits behind one setting, and the reply that explains a failure."""
    replies = []
    for parent in parents:
        effect = parent.effects[0] if parent.effects else None
        if parent.decision != "skipped":
            replies.append((_OUTCOMES[effect.outcome if effect else "unverified"], effect))
    for state in ("failed", "unverified", "updated"):
        if reply := next((item for item in replies if item[0] == state), None):
            return reply
    return "already_set", None


def _result(
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsCampaignUpdate],
    shown: Mapping[str, Any],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    campaigns = []
    for change in changes:
        name = change.resource_name
        check = shown.get(name)
        current = check.get("current") if isinstance(check, Mapping) else None
        current = current if isinstance(current, Mapping) else {}
        goal_keys = [edit.key for edit in _approved_edits(change, check) if edit.key != name]
        outcomes = {
            "conversion_goals": _outcome([parents[key] for key in goal_keys]),
            None: _outcome([parents[name]] if name in parents else []),
        }
        after = result.after.get(name)
        after_settings = card_settings(after) if after is not None else {}
        reference = change.campaign
        after_goals = goals_from_values(reference.customer_id, reference.campaign_id, result.after)
        if after_goals is not None:
            after_settings["conversion_goals"] = after_goals.card()
        settings = []
        for setting, requested in _effective(change, current).items():
            outcome, _reply = outcomes.get(setting, outcomes[None])
            before = current.get(setting)
            settings.append(
                {
                    "setting": setting,
                    "before": before,
                    "requested": requested,
                    "after": before if outcome == "already_set" else after_settings.get(setting),
                    # With no check there is no live value to match, so null never reads as set.
                    "outcome": (
                        "already_set" if setting in current and before == requested else outcome
                    ),
                }
            )
        reply = next(
            (reply for state, reply in outcomes.values() if state in {"failed", "unverified"}),
            None,
        )
        campaigns.append(
            {
                "resource_name": name,
                "campaign_id": change.campaign.campaign_id,
                "name": _name(change, check),
                # Every setting that was sent has a value read after it.
                "read_back": all(
                    item["outcome"] == "already_set" or item["setting"] in after_settings
                    for item in settings
                ),
                "settings": settings,
                "error_code": reply.error_code if reply is not None else None,
                "message": reply.message if reply is not None else None,
            }
        )
    portfolios = {
        name: {"resource_name": name, "name": str(item.get("name") or "Portfolio strategy")}
        for check in shown.values()
        if isinstance(check, Mapping) and isinstance(check.get("portfolios"), Mapping)
        for name, item in check["portfolios"].items()
        if isinstance(item, Mapping)
    }
    return {
        "account_id": entry.external_id,
        "currency": account_facts(entry).currency,
        "portfolios": list(portfolios.values()),
        "campaigns": campaigns,
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts and, per campaign, its live settings and Google's dry run."""
    request = GoogleAdsUpdateCampaignsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsCampaignUpdate]] = defaultdict(list)
    for change in request.changes:
        by_account[change.campaign.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    for customer_id, changes in by_account.items():
        checks.update(await _account_checks(deps, entries.get(customer_id), changes))
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {**args, "_accounts": accounts, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    changes: Sequence[GoogleAdsCampaignUpdate],
) -> dict[str, dict[str, Any]]:
    """Reads one account's campaigns and dry runs the changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        today = account_facts(entry).today()
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        account = {"customer_id": entry.external_id, "login_customer_id": login_customer_id(entry)}
        campaign_ids = [change.campaign.campaign_id for change in changes]
        live = await read_campaign_settings(client, **account, campaign_ids=campaign_ids)
        # Read for every campaign, so the card can offer goals on one that doesn't change them.
        goals = await read_campaign_goals(client, **account, campaign_ids=campaign_ids)
        portfolios = await _read_portfolios(client, entry, changes, live)
        problems = {
            change.resource_name: _setting_problems(
                change, item, goals.get(item.campaign_id), today, portfolios
            )
            for change in changes
            if (item := live.get(change.resource_name)) is not None
        }
        rejected = await _dry_run(client, entry, changes, live, goals, problems)
        notes = await _bidding_notes(client, entry, changes, live, problems, portfolios)
    except (IntegrationError, LookupError):
        return {change.resource_name: {"unavailable": True} for change in changes}
    return {
        change.resource_name: _check(
            change,
            live.get(change.resource_name),
            goals.get(change.campaign.campaign_id),
            problems.get(change.resource_name, {}),
            rejected.get(change.resource_name),
            notes.get(change.resource_name, []),
            portfolios,
        )
        for change in changes
    }


async def _read_portfolios(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsCampaignUpdate],
    live: Mapping[str, LiveCampaignSettings],
) -> dict[str, dict[str, str]]:
    """Reads the live portfolio strategies the campaigns use now or would move to."""
    names: set[str] = set()
    for change in changes:
        requested, item = change.requested.get("bidding"), live.get(change.resource_name)
        if requested is None:
            continue
        for bidding in (requested, item.settings()["bidding"] if item else {}):
            if bidding.get("strategy") == "PORTFOLIO":
                names.add(bidding["portfolio"])
    ids = sorted(name.rsplit("/", 1)[-1] for name in names if name.rsplit("/", 1)[-1].isdigit())
    portfolios: dict[str, dict[str, str]] = {}
    for start in range(0, len(ids), MAX_BIDDING_STRATEGY_LOOKUP):
        batch = ids[start : start + MAX_BIDDING_STRATEGY_LOOKUP]
        for strategy in await list_bidding_strategies(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            bidding_strategy_ids=batch,
            limit=len(batch),
        ):
            name = f"customers/{entry.external_id}/biddingStrategies/{strategy.get('id')}"
            portfolios[name] = {
                "name": str(strategy.get("name") or "Portfolio strategy"),
                "type": str(strategy.get("type") or ""),
            }
    return portfolios


async def _dry_run(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsCampaignUpdate],
    live: Mapping[str, LiveCampaignSettings],
    goals: Mapping[str, LiveCampaignGoals],
    problems: Mapping[str, Mapping[CampaignSetting, str]],
) -> dict[str, str]:
    """Returns Google's rejection per campaign, asking only about campaigns with no problem yet."""
    checked: list[FieldChange] = []
    values: dict[str, Mapping[str, Any]] = {}
    # The campaign each edit belongs to, since a campaign's goals are objects of their own.
    owners: dict[str, str] = {}
    for change in changes:
        name = change.resource_name
        item = live.get(name)
        if item is None or _campaign_problem(item) is not None or problems.get(name):
            continue
        campaign_goals = goals.get(item.campaign_id)
        edits = _edits(change, _current(item, campaign_goals), item.values, campaign_goals)
        checked.extend(edits)
        owners.update(dict.fromkeys((edit.key for edit in edits), name))
        values[name] = item.values
        if campaign_goals is not None:
            values.update(campaign_goals.values())
    if not checked:
        return {}

    async def read(edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return values

    prepared = await prepare_edits(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        edits=checked,
        read=read,
        operation=_OPERATION,
    )
    rejected: dict[str, str] = {}
    for edit in prepared:
        if edit.refused:
            rejected.setdefault(owners[edit.key], f"Google says: {edit.refused}")
    return rejected


async def _bidding_notes(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Sequence[GoogleAdsCampaignUpdate],
    live: Mapping[str, LiveCampaignSettings],
    problems: Mapping[str, Mapping[CampaignSetting, str]],
    portfolios: Portfolios,
) -> dict[str, list[str]]:
    """For each strategy change, its ad groups' own bids and, if needed, recent conversions."""
    moving: dict[str, tuple[GoogleAdsCampaignUpdate, Bidding, Bidding, str | None]] = {}
    for change in changes:
        item = live.get(change.resource_name)
        if item is None or "bidding" in problems.get(change.resource_name, {}):
            continue
        current = item.settings()
        bidding, _problem = _bidding(change, current)
        if bidding is not None and changes_strategy(bidding, current["bidding"]):
            kind = portfolios.get(str(bidding.get("portfolio")), {}).get("type")
            moving[item.campaign_id] = (change, bidding, current["bidding"], kind)
    if not moving:
        return {}
    account = {"customer_id": entry.external_id, "login_customer_id": login_customer_id(entry)}
    ad_groups = await read_ad_group_bids(client, **account, campaign_ids=list(moving))
    wanted = [
        key for key, (_c, bidding, _w, kind) in moving.items() if needs_conversions(bidding, kind)
    ]
    conversions = await read_conversions(client, **account, campaign_ids=wanted) if wanted else {}
    return {
        change.resource_name: bidding_notes(
            bidding,
            current,
            ad_groups=ad_groups.get(key, AdGroupBids()),
            conversions=conversions.get(key, 0.0) if key in wanted else None,
            portfolio_type=kind,
        )
        for key, (change, bidding, current, kind) in moving.items()
    }


def _check(
    change: GoogleAdsCampaignUpdate,
    live: LiveCampaignSettings | None,
    goals: LiveCampaignGoals | None,
    problems: Mapping[CampaignSetting, str],
    rejected: str | None,
    notes: Sequence[str],
    portfolios: Portfolios,
) -> dict[str, Any]:
    """Builds the card's view of one campaign, and the live values approval plans against."""
    current = _current(live, goals) if live else {}
    bidding, _problem = _bidding(change, current)
    own_fields = bool(change.requested.keys() - {"conversion_goals"})
    return {
        "unavailable": False,
        "name": change.campaign.label if live is None else live.values.get("name"),
        "status": live.status if live else None,
        "channel": live.channel if live else None,
        "current": current,
        "requested": change.requested,
        # What approval plans against, in Google's terms, for the paths the change reads.
        "values": (
            _campaign_edit(change, current, live.values).live(live.values) or {}
            if live and own_fields
            else {}
        ),
        # The same for the campaign's goals, by resource name, when the change sets them.
        "goal_values": (
            goals.values() if goals is not None and "conversion_goals" in change.requested else {}
        ),
        # Every goal the campaign can bid for, for the card to choose from.
        "goals": goals.options() if goals is not None else [],
        "problem": _campaign_problem(live) or rejected,
        "problems": dict(problems),
        "notes": {"bidding": list(notes)} if notes else {},
        # A strategy change restarts Google's learning, which the card counts in its banner.
        "learning": bool(
            live and bidding is not None and changes_strategy(bidding, current["bidding"])
        ),
        "portfolios": {name: dict(item) for name, item in portfolios.items()},
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_campaigns",
    function=google_ads_update_campaigns,
    description=(
        "Change settings on existing Google Ads campaigns of any type, up to 50 campaigns per "
        "call, in one approval. Each entry names one campaign and only the settings that "
        "change: name; start_date and end_date as YYYY-MM-DD in the account time zone, with "
        'end_date "none" to run with no end date; url_options with final_url_suffix, '
        "tracking_template, and custom_parameters (up to 8 key and value pairs, replacing the "
        "campaign's list), where an empty value clears it; networks with search_partners "
        "(Search and Shopping campaigns) and display_expansion (Search campaigns), each on or "
        "off; video_pages (Performance Max campaigns), up to 20 pages on the site, a YouTube "
        "channel, or a social profile that Google may take the advertiser's own videos from, "
        "replacing the campaign's list, where an empty list turns that off; never add pages "
        "unless the user explicitly asks, because listing a page confirms the advertiser owns "
        "the rights to its videos; final_url_expansion and text_customisation (Performance Max "
        "campaigns), each on or off, where Google customises text whenever final URL expansion "
        "is on, so turning text_customisation off needs final_url_expansion off too; "
        'conversion_goals, either "account" to bid for the account\'s goals or a list of '
        "category and origin pairs, such as PURCHASE and WEBSITE, that become the only goals "
        "this campaign bids for; and bidding. "
        "bidding is one of MANUAL_CPC; MAXIMIZE_CLICKS with optional "
        "max_cpc; MAXIMIZE_CONVERSIONS with optional target_cpa; MAXIMIZE_CONVERSION_VALUE "
        "with optional target_roas (a ratio, so 3.5 is 350%); TARGET_IMPRESSION_SHARE "
        "(Search only) with location, share_percent, and max_cpc; PORTFOLIO with a portfolio "
        "bidding strategy reference from the same account; or TARGETS with target_cpa, "
        "target_roas, or max_cpc to change only targets on the current strategy. Money is in "
        "the account currency. Leaving out an optional target removes it. A campaign that has "
        "started can't change its start date, and new dates can't be in the past. Status, "
        "budgets, targeting, removal, brand guidelines, and custom conversion goals aren't "
        "supported here. Each result reports what "
        "Google Ads shows after the change."
    ),
    provider="google_ads",
    label="Update Google Ads Campaigns",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=120,
    output_model=GoogleAdsUpdateCampaignsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateCampaignsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Campaigns",
        completed_label="Updated Google Ads Campaigns",
        failed_label="Couldn't Update Google Ads Campaigns",
        approval_title="Change Campaign Settings",
        approval_prompt="The agent wants to change settings on these Google Ads campaigns.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Campaign Changes",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_campaign", "google_ads_bidding_strategy"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
