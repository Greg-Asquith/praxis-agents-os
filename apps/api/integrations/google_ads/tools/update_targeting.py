# apps/api/integrations/google_ads/tools/update_targeting.py

"""Approval-only tool that changes which locations and languages Google Ads campaigns target."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Annotated, Any

from pydantic import Field
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
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.criteria import (
    BID_MODIFIER_PATH,
    CriterionKind,
    CriterionType,
    LiveCampaignTargeting,
    LiveCriterion,
    criterion_key,
    radius_value,
    read_campaign_targeting,
)
from ..operations.edits import (
    CriterionChange,
    Edit,
    EditResult,
    FieldChange,
    apply_edits,
    prepare_edits,
)
from ..operations.search_targeting import read_languages, read_locations
from .schemas.targeting import (
    MAX_TARGETING_CHANGES,
    GoogleAdsTargetingChange,
    GoogleAdsUpdateTargetingOutput,
    GoogleAdsUpdateTargetingRequest,
)
from .utils.accounts import NOT_SHOWN, approval_accounts, writable_entries
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "update_targeting"
_IDENTITY = ("object",)
_TYPES: tuple[CriterionType, ...] = ("LOCATION", "PROXIMITY", "LANGUAGE")
_SETTING_PATH = "geoTargetTypeSetting.positiveGeoTargetType"
# One audit event holds 2,500 records, and moving a place between lists takes two.
_MAX_EDITS = 2_500
# How many of a campaign's current locations the card lists by name.
_MAX_SHOWN = 100
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}

_MISSING = "This campaign no longer exists in Google Ads."
_REMOVED = "This campaign has been removed, so its targeting can't change."
_NO_LOCATION = (
    "This would leave the campaign with no location, so its ads could show anywhere. Keep at "
    "least one location."
)
# Google refuses to add these, and ignores any left on the campaign from before.
_SEARCH_LANGUAGES = "Search campaigns can't target languages. Google matches each ad's language."
_UNKNOWN_LOCATION = "Google Ads doesn't recognise this location."
_UNKNOWN_LANGUAGE = "Google Ads doesn't recognise this language."
_TOO_MANY = (
    f"This would make more than {_MAX_EDITS:,} changes in one request. Change fewer campaigns."
)


@dataclass(frozen=True, slots=True)
class _Planned:
    """One edit with what the card and the result say about it."""

    edit: Edit
    # The request field and item it came from, so a rejection can name them.
    field: str
    item: str
    setting: str
    action: str
    name: str
    bid_adjustment: int | None = None
    previous_bid_adjustment: int | None = None


def _percent(modifier: float) -> int:
    return round((modifier - 1) * 100)


def _modifier(percent: int) -> float:
    return round(1 + percent / 100, 2)


def _criterion_change(
    campaign: str,
    action: str,
    kind: CriterionKind,
    value: str,
    criteria: Mapping[str, LiveCriterion],
    body: Mapping[str, Any] | None = None,
) -> CriterionChange:
    """Builds an add or remove with the live resource name the operator was shown."""
    key = criterion_key(campaign, kind, value)
    live = criteria.get(key)
    return CriterionChange(
        resource="campaignCriterion",
        action="add" if action == "add" else "remove",
        key=key,
        owner=campaign,
        criterion={"campaign": campaign, **body} if body else {},
        before=live.resource_name if live else None,
    )


def _bid_or_add(
    campaign: str,
    kind: CriterionKind,
    value: str,
    body: Mapping[str, Any],
    bid_adjustment: int | None,
    criteria: Mapping[str, LiveCriterion],
) -> tuple[Edit, str, int | None]:
    """Adds the criterion, or changes the adjustment on one that's already there."""
    live = criteria.get(criterion_key(campaign, kind, value))
    if live is not None and bid_adjustment is not None:
        edit = FieldChange(
            resource="campaignCriterion",
            resource_name=live.resource_name,
            requested={BID_MODIFIER_PATH: _modifier(bid_adjustment)},
            before={BID_MODIFIER_PATH: live.bid_modifier},
        )
        return edit, "change_bid", _percent(live.bid_modifier)
    create = dict(body)
    if bid_adjustment:
        create[BID_MODIFIER_PATH] = _modifier(bid_adjustment)
    return _criterion_change(campaign, "add", kind, value, criteria, create), "add", None


def _plan(
    change: GoogleAdsTargetingChange,
    criteria: Mapping[str, LiveCriterion],
    location_setting: str | None,
    names: Mapping[str, Mapping[str, str]],
) -> list[_Planned]:
    """Compiles one campaign's request into edits, with removals first.

    Google can't change a criterion's value or its excluded flag, so moving a place between
    the included and excluded lists is a removal and an add, sent in that order.
    """
    campaign = _campaign_name(change)
    planned = [
        *_location_plan(change, campaign, criteria, names["locations"]),
        *_radius_plan(change, campaign, criteria),
        *_language_plan(change, campaign, criteria, names["languages"]),
    ]
    if change.location_setting is not None:
        edit = FieldChange(
            resource="campaign",
            resource_name=campaign,
            requested={_SETTING_PATH: change.location_setting},
            before={_SETTING_PATH: location_setting},
        )
        planned.append(
            _Planned(
                edit=edit,
                field="location_setting",
                item=change.location_setting,
                setting="location_setting",
                action="set",
                name=change.location_setting,
            )
        )
    # Sorting is stable, so each removal stays in request order ahead of every add.
    planned.sort(key=lambda item: item.action != "remove")
    keys = [item.edit.key for item in planned]
    if len(set(keys)) != len(keys):
        raise ModelRetry("A radius is being both added and removed. Keep one of those changes.")
    return _grouped_places(planned, campaign)


def _grouped_places(planned: list[_Planned], campaign: str) -> list[_Planned]:
    """Sends a campaign's place changes together when it loses a place, so a rejected add
    can't leave the removals applied."""
    places = {"locations", "excluded_locations", "radius"}
    if not any(
        item.action == "remove" and item.setting in {"locations", "radius"} for item in planned
    ):
        return planned
    return [
        replace(item, edit=replace(item.edit, atomic_group=campaign))
        if isinstance(item.edit, CriterionChange) and item.setting in places
        else item
        for item in planned
    ]


def _campaign_name(change: GoogleAdsTargetingChange) -> str:
    reference = change.campaign
    return f"customers/{reference.customer_id}/campaigns/{reference.campaign_id}"


def _location_plan(
    change: GoogleAdsTargetingChange,
    campaign: str,
    criteria: Mapping[str, LiveCriterion],
    names: Mapping[str, str],
) -> list[_Planned]:
    def removal(field: str, key: str, kind: CriterionKind, name: str) -> _Planned:
        return _Planned(
            edit=_criterion_change(campaign, "remove", kind, key, criteria),
            field=field,
            item=key,
            setting="excluded_locations" if kind == "excluded_location" else "locations",
            action="remove",
            name=name,
        )

    def held(kind: CriterionKind, key: str) -> bool:
        return criterion_key(campaign, kind, key) in criteria

    planned: list[_Planned] = []
    for item in change.remove_locations:
        kind: CriterionKind = (
            "excluded_location" if held("excluded_location", item.key) else "location"
        )
        name = names.get(item.key) or item.name or item.key
        planned.append(removal("remove_locations", item.key, kind, name))
    for item in change.exclude_locations:
        name = names.get(item.key) or item.name or item.key
        if held("location", item.key):
            planned.append(removal("exclude_locations", item.key, "location", name))
        body = {"negative": True, "location": _location_value(item.key)}
        planned.append(
            _Planned(
                edit=_criterion_change(
                    campaign, "add", "excluded_location", item.key, criteria, body
                ),
                field="exclude_locations",
                item=item.key,
                setting="excluded_locations",
                action="add",
                name=name,
            )
        )
    for item in change.add_locations:
        name = names.get(item.key) or item.name or item.key
        if held("excluded_location", item.key):
            planned.append(removal("add_locations", item.key, "excluded_location", name))
        edit, action, previous = _bid_or_add(
            campaign,
            "location",
            item.key,
            {"location": _location_value(item.key)},
            item.bid_adjustment,
            criteria,
        )
        planned.append(
            _Planned(
                edit=edit,
                field="add_locations",
                item=item.key,
                setting="locations",
                action=action,
                name=name,
                bid_adjustment=item.bid_adjustment,
                previous_bid_adjustment=previous,
            )
        )
    return planned


def _location_value(key: str) -> dict[str, str]:
    return {"geoTargetConstant": f"geoTargetConstants/{key}"}


def _radius_plan(
    change: GoogleAdsTargetingChange, campaign: str, criteria: Mapping[str, LiveCriterion]
) -> list[_Planned]:
    live_radius = {
        criterion.criterion_id: criterion
        for criterion in criteria.values()
        if criterion.kind == "radius"
    }
    planned: list[_Planned] = []
    for criterion_id in change.remove_radius:
        live = live_radius.get(criterion_id)
        planned.append(
            _Planned(
                edit=_criterion_change(
                    campaign,
                    "remove",
                    "radius",
                    live.value if live else f"id-{criterion_id}",
                    criteria,
                ),
                field="remove_radius",
                item=criterion_id,
                setting="radius",
                action="remove",
                name=_radius_name(live.radius, live.units) if live else "Radius",
            )
        )
    for target in change.add_radius:
        latitude = round(target.latitude * 1_000_000)
        longitude = round(target.longitude * 1_000_000)
        value = radius_value(latitude, longitude, target.radius, target.units)
        body = {
            "proximity": {
                "geoPoint": {
                    "latitudeInMicroDegrees": latitude,
                    "longitudeInMicroDegrees": longitude,
                },
                "radius": target.radius,
                "radiusUnits": target.units,
            }
        }
        edit, action, previous = _bid_or_add(
            campaign, "radius", value, body, target.bid_adjustment, criteria
        )
        planned.append(
            _Planned(
                edit=edit,
                field="add_radius",
                item=value,
                setting="radius",
                action=action,
                name=target.label or _radius_name(target.radius, target.units),
                bid_adjustment=target.bid_adjustment,
                previous_bid_adjustment=previous,
            )
        )
    return planned


def _radius_name(radius: float | None, units: str | None) -> str:
    return f"{radius:g} {(units or 'kilometers').lower()}" if radius is not None else "Radius"


def _language_plan(
    change: GoogleAdsTargetingChange,
    campaign: str,
    criteria: Mapping[str, LiveCriterion],
    names: Mapping[str, str],
) -> list[_Planned]:
    planned = [
        _Planned(
            edit=_criterion_change(campaign, "remove", "language", item.key, criteria),
            field="remove_languages",
            item=item.key,
            setting="languages",
            action="remove",
            name=names.get(item.key) or item.name or item.key,
        )
        for item in change.remove_languages
    ]
    for item in change.add_languages:
        body = {"language": {"languageConstant": f"languageConstants/{item.key}"}}
        planned.append(
            _Planned(
                edit=_criterion_change(campaign, "add", "language", item.key, criteria, body),
                field="add_languages",
                item=item.key,
                setting="languages",
                action="add",
                name=names.get(item.key) or item.name or item.key,
            )
        )
    return planned


def _campaign_problem(
    live: LiveCampaignTargeting | None, planned: Sequence[_Planned]
) -> str | None:
    if live is None:
        return _MISSING
    if live.status == "REMOVED":
        return _REMOVED
    positive = {
        key for key, criterion in live.criteria.items() if criterion.kind in {"location", "radius"}
    }
    if not positive:
        return None
    left = set(positive)
    for item in planned:
        edit = item.edit
        if isinstance(edit, CriterionChange) and item.setting in {"locations", "radius"}:
            if edit.action == "remove":
                left.discard(edit.key)
            else:
                left.add(edit.key)
    return None if left else _NO_LOCATION


def _item_problem(
    item: _Planned,
    live: LiveCampaignTargeting | None,
    names: Mapping[str, Mapping[str, str]],
) -> str | None:
    if item.field == "add_languages":
        if live is not None and live.channel == "SEARCH":
            return _SEARCH_LANGUAGES
        if item.item not in names["languages"]:
            return _UNKNOWN_LANGUAGE
    if item.field in {"add_locations", "exclude_locations"} and item.item not in names["locations"]:
        return _UNKNOWN_LOCATION
    return None


def _with_refusals(
    planned: Sequence[_Planned],
    live: LiveCampaignTargeting | None,
    names: Mapping[str, Mapping[str, str]],
    shown_problem: str | None = None,
) -> tuple[list[_Planned], str | None]:
    """Marks what mustn't be sent, and returns the problem that stops the whole campaign.

    An add that can't be sent doesn't count as a location the campaign keeps.
    """
    sendable = [item for item in planned if _item_problem(item, live, names) is None]
    problem = shown_problem or _campaign_problem(live, sendable)
    refused: list[_Planned] = []
    for item in planned:
        reason = problem or _item_problem(item, live, names)
        refused.append(replace(item, edit=replace(item.edit, refused=reason)) if reason else item)
    return refused, problem


async def _read_names(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Iterable[GoogleAdsTargetingChange],
    live: Mapping[str, LiveCampaignTargeting],
) -> dict[str, dict[str, str]]:
    """Reads Google's names for what the request names and what each campaign shows."""
    changes = list(changes)
    requested = [
        item.key
        for change in changes
        for items in (change.add_locations, change.exclude_locations, change.remove_locations)
        for item in items
    ]
    shown = [key for targeting in live.values() for key in _shown_location_keys(targeting)]
    locations = (
        await read_locations(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            keys=[*requested, *shown],
        )
        if requested or shown
        else {}
    )
    languages = await read_languages(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry)
    )
    return {
        "locations": {key: option.name for key, option in locations.items()},
        "languages": {option.key: option.name for option in languages},
    }


def _shown_location_keys(targeting: LiveCampaignTargeting) -> list[str]:
    places = [
        criterion.value
        for criterion in targeting.criteria.values()
        if criterion.kind in {"location", "excluded_location"}
    ]
    return places[:_MAX_SHOWN]


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, campaign_ids: Sequence[str]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await read_campaign_targeting(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            campaign_ids=campaign_ids,
            types=_TYPES,
        )
        return {key: value for item in live.values() for key, value in item.values().items()}

    return read


async def google_ads_update_targeting(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsTargetingChange],
        Field(
            min_length=1,
            max_length=MAX_TARGETING_CHANGES,
            description="One entry per campaign, with only what changes.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateTargetingRequest, {"changes": changes})
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
        client: GoogleAdsClient | None = None
        planned: dict[str, list[_Planned]] = {}
        names_by_campaign: dict[str, str] = {}
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, pending
            client = await google_ads_client(ctx, entry)
            # Accounts change between the check and the send, so read them again as approved.
            live = await read_campaign_targeting(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                campaign_ids=[change.campaign.campaign_id for change in account_changes],
                types=_TYPES,
            )
            for change in account_changes:
                campaign_id = change.campaign.campaign_id
                planned[campaign_id] = _approved_plan(change, shown, live.get(campaign_id))
                targeting = live.get(campaign_id)
                names_by_campaign[campaign_id] = (
                    targeting.name if targeting else change.campaign.label
                )
            pending = _pending_detail(entry, planned)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not planned:
                raise RuntimeError("Google Ads targeting preparation did not complete")
            items = [item for campaign in planned.values() for item in campaign]
            try:
                result = await apply_edits(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    edits=[item.edit for item in items],
                    read=_reader(client, entry, list(planned)),
                    family="targeting",
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, result.ledger, identity_keys=_IDENTITY)
            data = _result(entry, planned, names_by_campaign, result)
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                data,
                status=status,
                external_ref=",".join(result.ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=data if status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_targeting",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.campaign for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _approved_plan(
    change: GoogleAdsTargetingChange,
    shown: Mapping[str, Any],
    live: LiveCampaignTargeting | None,
) -> list[_Planned]:
    """Plans against what the approver saw, so `apply_edits` refuses anything changed since."""
    checks = shown.get("campaigns")
    check = checks.get(_campaign_name(change)) if isinstance(checks, Mapping) else None
    names = shown.get("names")
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or not isinstance(names, Mapping)
    ):
        planned = _plan(change, {}, None, {"locations": {}, "languages": {}})
        return [replace(item, edit=replace(item.edit, refused=NOT_SHOWN)) for item in planned]
    criteria = {
        key: LiveCriterion(**values) for key, values in (check.get("criteria") or {}).items()
    }
    planned = _plan(change, criteria, check.get("location_setting"), names)
    # Google's answers aren't asked for again, so a problem they caused still stands.
    shown_problem = check.get("problem")
    return _with_refusals(
        planned, live, names, shown_problem if isinstance(shown_problem, str) else None
    )[0]


def _pending_detail(
    entry: ResolvedContextEntry, planned: Mapping[str, Sequence[_Planned]]
) -> PendingIntegrationOperationDetail:
    """Records each change by key; names of places stay out of the audit record."""
    groups: dict[tuple[str, str], list[IntegrationOperationIntent]] = defaultdict(list)
    for items in planned.values():
        for item in items:
            groups[item.setting, item.action].append(
                IntegrationOperationIntent(fields={"object": item.edit.key})
            )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{setting}:{action}",
                action=action,
                entity_type="google_ads_campaign_targeting",
                items=items,
            )
            for (setting, action), items in groups.items()
        ],
    )


def _result(
    entry: ResolvedContextEntry,
    planned: Mapping[str, Sequence[_Planned]],
    campaign_names: Mapping[str, str],
    result: EditResult,
) -> dict[str, Any]:
    parents = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for campaign_id, items in planned.items():
        for item in items:
            parent = parents[item.edit.key]
            effect = parent.effects[0] if parent.effects else None
            outcome = (
                "already_set"
                if parent.decision == "skipped"
                else _OUTCOMES[effect.outcome if effect else "unverified"]
            )
            row = rows.setdefault(
                (campaign_id, item.setting, item.action, outcome),
                {
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_names[campaign_id],
                    "setting": item.setting,
                    "action": item.action,
                    "outcome": outcome,
                    "count": 0,
                    "items": [],
                    "error_code": effect.error_code if effect else None,
                    "message": effect.message if effect else None,
                },
            )
            row["count"] += 1
            if len(row["items"]) < 10:
                row["items"].append(
                    {
                        "name": item.name,
                        "bid_adjustment": item.bid_adjustment,
                        "previous_bid_adjustment": item.previous_bid_adjustment,
                    }
                )
    return {"account_id": entry.external_id, "outcomes": list(rows.values())}


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts, what each campaign targets now, and Google's dry run."""
    request = GoogleAdsUpdateTargetingRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsTargetingChange]] = defaultdict(list)
    for change in request.changes:
        by_account[change.campaign.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    campaigns: dict[str, dict[str, Any]] = {}
    names: dict[str, dict[str, str]] = {"locations": {}, "languages": {}}
    for customer_id, changes in by_account.items():
        account_campaigns, account_names = await _account_checks(
            deps, entries.get(customer_id), changes
        )
        campaigns.update(account_campaigns)
        for kind, values in account_names.items():
            names[kind].update(values)
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {
        **args,
        "_accounts": accounts,
        "_checks": {"campaigns": campaigns, "names": names},
    }


async def _account_checks(
    deps: RuntimeDeps,
    entry: ResolvedContextEntry | None,
    changes: Sequence[GoogleAdsTargetingChange],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    """Reads one account and dry runs its changes; an unreadable account is unavailable."""
    try:
        if entry is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=entry
        )
        live = await read_campaign_targeting(
            client,
            customer_id=entry.external_id,
            login_customer_id=login_customer_id(entry),
            campaign_ids=[change.campaign.campaign_id for change in changes],
            types=_TYPES,
        )
        names = await _read_names(client, entry, changes, live)
        plans = [_checked_plan(change, live, names) for change in changes]
        edits = [item.edit for planned, _problem in plans for item in planned]
        if len(edits) > _MAX_EDITS:
            raise ModelRetry(_TOO_MANY)
        values = {key: value for item in live.values() for key, value in item.values().items()}

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
    except (IntegrationError, LookupError):
        unavailable = {_campaign_name(change): {"unavailable": True} for change in changes}
        return unavailable, {"locations": {}, "languages": {}}
    results = {edit.key: edit for edit in prepared}
    return (
        {
            _campaign_name(change): _check(
                change, live.get(change.campaign.campaign_id), *plan, results, names
            )
            for change, plan in zip(changes, plans, strict=True)
        },
        names,
    )


def _checked_plan(
    change: GoogleAdsTargetingChange,
    live: Mapping[str, LiveCampaignTargeting],
    names: Mapping[str, Mapping[str, str]],
) -> tuple[list[_Planned], str | None]:
    targeting = live.get(change.campaign.campaign_id)
    planned = _plan(
        change,
        targeting.criteria if targeting else {},
        targeting.location_setting if targeting else None,
        names,
    )
    return _with_refusals(planned, targeting, names)


def _check(
    change: GoogleAdsTargetingChange,
    live: LiveCampaignTargeting | None,
    planned: Sequence[_Planned],
    problem: str | None,
    results: Mapping[str, Edit],
    names: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Builds the card's view of one campaign, and the live values approval plans against."""
    # An add Google rejected won't happen, so removals alongside it could leave no location.
    problem = problem or _campaign_problem(
        live, [item for item in planned if results[item.edit.key].refused is None]
    )
    item_problems: dict[tuple[str, str], str] = {}
    already: list[dict[str, str]] = []
    for item in planned:
        edit = results[item.edit.key]
        if edit.refused and edit.refused != problem:
            message = edit.refused
            if item.edit.refused is None:
                message = f"Google says: {message}"
            item_problems.setdefault((item.field, item.item), message)
        if edit.refused is None and edit.unchanged:
            already.append({"field": item.field, "key": item.item})
    criteria = live.criteria if live else {}
    touched = {key: asdict(criteria[key]) for item in planned if (key := item.edit.key) in criteria}
    by_resource = {criterion.resource_name: key for key, criterion in criteria.items()}
    for item in planned:
        key = by_resource.get(item.edit.key)
        if key is not None:
            touched[key] = asdict(criteria[key])
    places = [c for c in criteria.values() if c.kind in {"location", "excluded_location"}]
    return {
        "unavailable": False,
        "name": live.name if live else change.campaign.label,
        "channel": live.channel if live else None,
        "status": live.status if live else None,
        "problem": problem,
        "location_setting": live.location_setting if live else None,
        "locations": [
            {
                "key": place.value,
                "name": names["locations"].get(place.value, place.value),
                "excluded": place.kind == "excluded_location",
                "bid_adjustment": _percent(place.bid_modifier),
            }
            for place in places[:_MAX_SHOWN]
        ],
        "location_total": len(places),
        "radius": [
            {
                "criterion_id": c.criterion_id,
                "radius": c.radius,
                "units": c.units,
                "latitude": (c.latitude_micro or 0) / 1_000_000,
                "longitude": (c.longitude_micro or 0) / 1_000_000,
                "bid_adjustment": _percent(c.bid_modifier),
            }
            for c in criteria.values()
            if c.kind == "radius"
        ][:_MAX_SHOWN],
        "languages": [
            {"key": c.value, "name": names["languages"].get(c.value, c.value)}
            for c in criteria.values()
            if c.kind == "language"
        ],
        "item_problems": [
            {"field": field, "key": key, "message": message}
            for (field, key), message in item_problems.items()
        ],
        "already_set": already,
        # What approval plans against; only criteria this request touches.
        "criteria": touched,
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_targeting",
    function=google_ads_update_targeting,
    description=(
        "Change which locations and languages existing Google Ads campaigns target, up to 20 "
        "campaigns per call, in one approval. Each entry names one campaign and only what "
        "changes, as additions and removals. add_locations, exclude_locations, and "
        "remove_locations take location keys from google_ads_search_targeting; add_locations "
        "can set bid_adjustment as a percent from -90 to 900, and naming a location already "
        "targeted changes its adjustment. Excluding an included location, or adding an excluded "
        "one, moves it. add_radius takes latitude, longitude, radius, and units (MILES or "
        "KILOMETERS), with an optional label and bid_adjustment; remove_radius takes criterion "
        "IDs from google_ads_run_report. location_setting is PRESENCE_OR_INTEREST (people in, "
        "or showing interest in, a location) or PRESENCE (people in, or regularly in, a "
        "location). add_languages and remove_languages take language keys. Search campaigns "
        "can't add languages because Google matches each ad's language; a language left on one "
        "from before can be removed. A change that would leave a campaign with no location is "
        "refused, because its ads could then show anywhere. Each result reports what Google "
        "Ads shows after the change. Audiences, devices, and schedules aren't supported here."
    ),
    provider="google_ads",
    label="Update Google Ads Targeting",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=300,
    output_model=GoogleAdsUpdateTargetingOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsUpdateTargetingRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("changes",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Targeting",
        completed_label="Updated Google Ads Targeting",
        failed_label="Couldn't Update Google Ads Targeting",
        approval_title="Change Who Campaigns Reach",
        approval_prompt="The agent wants to change who these Google Ads campaigns reach.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="changes",
                label="Targeting Changes",
                editable=True,
                format="structured",
                # The first kind authorises a review; the card adds the other two from searches.
                entity_kinds=(
                    "google_ads_campaign",
                    "google_ads_location",
                    "google_ads_language",
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
