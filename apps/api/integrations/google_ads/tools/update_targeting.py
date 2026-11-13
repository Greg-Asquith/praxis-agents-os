# apps/api/integrations/google_ads/tools/update_targeting.py

"""Approval-only tool that changes where, when, and to whom Google Ads campaigns and ad groups show."""

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
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets

from ..client import GoogleAdsClient
from ..operations.criteria import (
    AD_GROUP_TYPES,
    AUDIENCE_FIELDS,
    BID_MODIFIER_PATH,
    DEMOGRAPHIC_FIELDS,
    EU_POLITICAL_PATH,
    EU_POLITICAL_UNANSWERED,
    RESTRICTIONS_PATH,
    SCHEDULE_MINUTES,
    CriterionKind,
    CriterionType,
    LiveCriterion,
    LiveTargeting,
    audience_value,
    criterion_key,
    demographic_value,
    radius_value,
    read_targeting,
    schedule_value,
)
from ..operations.edits import (
    STALE_MESSAGE,
    CriterionChange,
    Edit,
    EditResult,
    FieldChange,
    prepare_edits,
)
from ..operations.search_campaigns import eu_political_status
from ..operations.search_targeting import read_audiences, read_languages, read_locations
from .schemas.targeting import (
    MAX_TARGETING_CHANGES,
    GoogleAdsScheduleWindow,
    GoogleAdsTargetingChange,
    GoogleAdsUpdateTargetingOutput,
    GoogleAdsUpdateTargetingRequest,
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

_OPERATION = "update_targeting"
_TYPES: tuple[CriterionType, ...] = (
    "LOCATION",
    "PROXIMITY",
    "LANGUAGE",
    "DEVICE",
    "AD_SCHEDULE",
    *AD_GROUP_TYPES,
)
_SETTING_PATH = "geoTargetTypeSetting.positiveGeoTargetType"
# One audit event holds 2,500 records, and moving a place between lists takes two.
_MAX_EDITS = 2_500
# How many of a campaign's current locations the card lists by name.
_MAX_SHOWN = 100
_DEVICE_NAMES = {"MOBILE": "Mobile Phones", "DESKTOP": "Computers", "TABLET": "Tablets"}
_OUTCOMES = {"applied": "updated", "failed": "failed", "unverified": "unverified"}
# `eu_locations` names the locations Google wants a campaign's EU political answer for.
_NO_NAMES: dict[str, dict[str, str]] = {
    "locations": {},
    "languages": {},
    "audiences": {},
    "eu_locations": {},
}
_EU_POLITICAL = "contains_eu_political_advertising"

_MISSING = "This no longer exists in Google Ads."
_REMOVED = "This campaign has been removed, so its targeting can't change."
_AD_GROUP_REMOVED = "This ad group or its campaign has been removed, so its targeting can't change."
_NO_LOCATION = (
    "This would leave the campaign with no location, so its ads could show anywhere. Keep at "
    "least one location."
)
# Google refuses to add these, and ignores any left on the campaign from before.
_SEARCH_LANGUAGES = "Search campaigns can't target languages. Google matches each ad's language."
_UNKNOWN_LOCATION = "Google Ads doesn't recognise this location."
_UNKNOWN_LANGUAGE = "Google Ads doesn't recognise this language."
_UNKNOWN_AUDIENCE = "Google Ads doesn't recognise this audience in this account."
_IGNORED_BIDS = "This campaign's bidding strategy sets its own bids, so it ignores {what}."
_EXCLUDING_WORKS = " Excluding still works."
_TOO_MANY = (
    f"This would make more than {_MAX_EDITS:,} changes in one request. Change fewer campaigns."
)


@dataclass(frozen=True, slots=True)
class _Owner:
    """The campaign or ad group a change is on, with the resources its edits use."""

    name: str
    # `campaign` or `adGroup`: the mutate resource, and the criterion's field naming it.
    resource: str
    criterion: str
    customer_id: str

    @classmethod
    def of(cls, change: GoogleAdsTargetingChange) -> "_Owner":
        level = "adGroup" if change.ad_group is not None else "campaign"
        return cls(
            name=change.owner,
            resource=level,
            criterion=f"{level}Criterion",
            customer_id=change.reference.customer_id,
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
    # A removal that only makes way for the change beside it, so the result doesn't list it.
    shown: bool = True
    # The setting this item changes when several share one campaign or ad group update.
    path: str | None = None


def _percent(modifier: float) -> int:
    # An excluded device has a modifier of 0, which reads as -100%.
    return round((modifier - 1) * 100)


def _modifier(percent: int) -> float:
    return round(1 + percent / 100, 2)


def _criterion_change(
    owner: _Owner,
    action: str,
    kind: CriterionKind,
    value: str,
    criteria: Mapping[str, LiveCriterion],
    body: Mapping[str, Any] | None = None,
) -> CriterionChange:
    """Builds an add or remove with the live resource name the operator was shown."""
    key = criterion_key(owner.name, kind, value)
    live = criteria.get(key)
    return CriterionChange(
        resource=owner.criterion,
        action="add" if action == "add" else "remove",
        key=key,
        owner=owner.name,
        criterion={owner.resource: owner.name, **body} if body else {},
        before=live.resource_name if live else None,
    )


def _bid_change(owner: _Owner, live: LiveCriterion, modifier: float) -> FieldChange:
    return FieldChange(
        resource=owner.criterion,
        resource_name=live.resource_name,
        requested={BID_MODIFIER_PATH: modifier},
        before={BID_MODIFIER_PATH: live.bid_modifier},
    )


def _bid_or_add(
    owner: _Owner,
    kind: CriterionKind,
    value: str,
    body: Mapping[str, Any],
    bid_adjustment: int | None,
    criteria: Mapping[str, LiveCriterion],
) -> tuple[Edit, str, int | None]:
    """Adds the criterion, or changes the adjustment on one that's already there."""
    live = criteria.get(criterion_key(owner.name, kind, value))
    if live is not None and bid_adjustment is not None:
        return (
            _bid_change(owner, live, _modifier(bid_adjustment)),
            "change_bid",
            _percent(live.bid_modifier),
        )
    create = dict(body)
    if bid_adjustment:
        create[BID_MODIFIER_PATH] = _modifier(bid_adjustment)
    return _criterion_change(owner, "add", kind, value, criteria, create), "add", None


def _plan(
    change: GoogleAdsTargetingChange,
    criteria: Mapping[str, LiveCriterion],
    settings: Mapping[str, Any],
    names: Mapping[str, Mapping[str, str]],
) -> list[_Planned]:
    """Compiles one campaign's or ad group's request into edits, with removals first.

    Google can't change a criterion's value or its excluded flag, so moving a place between
    the included and excluded lists is a removal and an add, sent in that order. `settings`
    holds the live location setting, target restrictions, and EU political answer.
    """
    owner = _Owner.of(change)
    # Google refuses an EU location or a radius on a campaign that hasn't given its answer.
    declares = (
        change.campaign is not None
        and settings.get(EU_POLITICAL_PATH) == EU_POLITICAL_UNANSWERED
        and (
            bool(change.add_radius)
            or any(item.key in names["eu_locations"] for item in change.add_locations)
        )
    )
    planned = [
        *_location_plan(change, owner, criteria, names["locations"]),
        *_radius_plan(change, owner, criteria),
        *_language_plan(change, owner, criteria, names["languages"]),
        *_device_plan(change, owner, criteria),
        *_schedule_plan(change, owner, criteria),
        *_audience_plan(change, owner, criteria, names["audiences"]),
        *_demographic_plan(change, owner, criteria),
        *_settings_plan(change, owner, settings, declares=declares),
    ]
    # Sorting is stable, so each removal stays in request order ahead of every add, and the
    # EU political answer goes ahead of the places that need it.
    planned.sort(
        key=lambda item: 0 if item.action == "remove" else 1 if item.field == _EU_POLITICAL else 2
    )
    keys = [item.edit.key for item in planned if item.path is None]
    if len(set(keys)) != len(keys):
        raise ModelRetry("A radius is being both added and removed. Keep one of those changes.")
    return _grouped_places(planned, owner.name)


def _grouped_places(planned: list[_Planned], campaign: str) -> list[_Planned]:
    """Sends a campaign's place changes together when it loses a place, so a rejected add
    can't leave the removals applied, or with the EU political answer they need."""
    places = {"locations", "excluded_locations", "radius"}
    declares = any(item.field == _EU_POLITICAL for item in planned)
    if not declares and not any(
        item.action == "remove" and item.setting in {"locations", "radius"} for item in planned
    ):
        return planned
    return [
        replace(item, edit=replace(item.edit, atomic_group=campaign))
        # The answer shares the campaign's one update with its other settings.
        if (isinstance(item.edit, CriterionChange) and item.setting in places)
        or (declares and item.path is not None)
        else item
        for item in planned
    ]


def _settings_plan(
    change: GoogleAdsTargetingChange, owner: _Owner, live: Mapping[str, Any], *, declares: bool
) -> list[_Planned]:
    """The location setting, audience mode, and EU political answer, as one update to the
    campaign or ad group."""
    requested: dict[str, Any] = {}
    items: list[tuple[str, str, str]] = []
    if declares:
        status = eu_political_status(change.contains_eu_political_advertising is True)
        requested[EU_POLITICAL_PATH] = status
        items.append((_EU_POLITICAL, status, EU_POLITICAL_PATH))
    if change.location_setting is not None:
        requested[_SETTING_PATH] = change.location_setting
        items.append(("location_setting", change.location_setting, _SETTING_PATH))
    if change.audience_mode is not None:
        # Google takes the whole list, so every other dimension keeps its live value.
        kept = [
            dict(item)
            for item in live.get(RESTRICTIONS_PATH) or ()
            if item["targetingDimension"] != "AUDIENCE"
        ]
        bid_only = change.audience_mode == "OBSERVATION"
        requested[RESTRICTIONS_PATH] = sorted(
            [*kept, {"targetingDimension": "AUDIENCE", "bidOnly": bid_only}],
            key=lambda item: item["targetingDimension"],
        )
        items.append(("audience_mode", change.audience_mode, RESTRICTIONS_PATH))
    if not requested:
        return []
    edit = FieldChange(
        resource=owner.resource,
        resource_name=owner.name,
        requested=requested,
        before={path: live.get(path) for path in requested},
    )
    return [
        _Planned(
            edit=edit, field=field, item=value, setting=field, action="set", name=value, path=path
        )
        for field, value, path in items
    ]


def _location_plan(
    change: GoogleAdsTargetingChange,
    owner: _Owner,
    criteria: Mapping[str, LiveCriterion],
    names: Mapping[str, str],
) -> list[_Planned]:
    def removal(field: str, key: str, kind: CriterionKind, name: str) -> _Planned:
        return _Planned(
            edit=_criterion_change(owner, "remove", kind, key, criteria),
            field=field,
            item=key,
            setting="excluded_locations" if kind == "excluded_location" else "locations",
            action="remove",
            name=name,
        )

    def held(kind: CriterionKind, key: str) -> bool:
        return criterion_key(owner.name, kind, key) in criteria

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
                edit=_criterion_change(owner, "add", "excluded_location", item.key, criteria, body),
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
            owner,
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
    change: GoogleAdsTargetingChange, owner: _Owner, criteria: Mapping[str, LiveCriterion]
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
                    owner,
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
            owner, "radius", value, body, target.bid_adjustment, criteria
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
    owner: _Owner,
    criteria: Mapping[str, LiveCriterion],
    names: Mapping[str, str],
) -> list[_Planned]:
    planned = [
        _Planned(
            edit=_criterion_change(owner, "remove", "language", item.key, criteria),
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
                edit=_criterion_change(owner, "add", "language", item.key, criteria, body),
                field="add_languages",
                item=item.key,
                setting="languages",
                action="add",
                name=names.get(item.key) or item.name or item.key,
            )
        )
    return planned


def _device_plan(
    change: GoogleAdsTargetingChange, owner: _Owner, criteria: Mapping[str, LiveCriterion]
) -> list[_Planned]:
    """Sets each device's adjustment; a modifier of 0 excludes the device."""
    planned: list[_Planned] = []
    for target in change.devices:
        modifier = 0.0 if target.excluded else _modifier(target.bid_adjustment or 0)
        key = criterion_key(owner.name, "device", target.device)
        live = criteria.get(key)
        edit: Edit
        if live is not None:
            edit = _bid_change(owner, live, modifier)
        elif modifier == 1.0:
            # No criterion means no adjustment, so there's nothing to send.
            edit = CriterionChange(
                resource=owner.criterion, action="remove", key=key, owner=owner.name
            )
        else:
            body = {"device": {"type": target.device}, BID_MODIFIER_PATH: modifier}
            edit = _criterion_change(owner, "add", "device", target.device, criteria, body)
        planned.append(
            _Planned(
                edit=edit,
                field="devices",
                item=target.device,
                setting="devices",
                action="set",
                name=_DEVICE_NAMES[target.device],
                bid_adjustment=_percent(modifier),
                previous_bid_adjustment=_percent(live.bid_modifier if live else 1.0),
            )
        )
    return planned


def _schedule_plan(
    change: GoogleAdsTargetingChange, owner: _Owner, criteria: Mapping[str, LiveCriterion]
) -> list[_Planned]:
    """Diffs the requested week against the live one, and sends the result as one unit.

    A window's times can't be updated, so an unchanged window is kept, a new adjustment on
    the same times is an update, and every other change is a removal and an add.
    """
    if change.ad_schedule is None and not change.clear_ad_schedule:
        return []
    live = {c.value: c for c in criteria.values() if c.kind == "schedule"}
    wanted = {
        schedule_value(window.day, window.start, window.end): window
        for window in change.ad_schedule or ()
    }
    group = f"{owner.name}#ad_schedule"
    planned = [
        _Planned(
            edit=replace(
                _criterion_change(owner, "remove", "schedule", value, criteria),
                atomic_group=group,
            ),
            field="ad_schedule",
            item=value,
            setting="ad_schedule",
            action="remove",
            name=_window_name(value),
            bid_adjustment=_percent(criterion.bid_modifier),
        )
        for value, criterion in live.items()
        if value not in wanted
    ]
    for value, window in wanted.items():
        modifier = _modifier(window.bid_adjustment or 0)
        current = live.get(value)
        edit: Edit
        if current is not None:
            edit = replace(_bid_change(owner, current, modifier), atomic_group=group)
            action = "add" if current.bid_modifier == modifier else "change_bid"
        else:
            body: dict[str, Any] = {"adSchedule": _schedule_body(window)}
            if modifier != 1.0:
                body[BID_MODIFIER_PATH] = modifier
            edit = replace(
                _criterion_change(owner, "add", "schedule", value, criteria, body),
                atomic_group=group,
            )
            action = "add"
        planned.append(
            _Planned(
                edit=edit,
                field="ad_schedule",
                item=value,
                setting="ad_schedule",
                action=action,
                name=_window_name(value),
                bid_adjustment=window.bid_adjustment,
                previous_bid_adjustment=_percent(current.bid_modifier) if current else None,
            )
        )
    if not planned:
        # No windows to clear, so one change that sends nothing records the schedule as set.
        planned.append(
            _Planned(
                edit=CriterionChange(
                    resource=owner.criterion,
                    action="remove",
                    key=criterion_key(owner.name, "schedule", "none"),
                    owner=owner.name,
                ),
                field="ad_schedule",
                item="ad_schedule",
                setting="ad_schedule",
                action="remove",
                name="Ad schedule",
            )
        )
    return planned


def _schedule_body(window: GoogleAdsScheduleWindow) -> dict[str, Any]:
    start_hour, start_minute = (int(part) for part in window.start.split(":"))
    end_hour, end_minute = (int(part) for part in window.end.split(":"))
    return {
        "dayOfWeek": window.day,
        "startHour": start_hour,
        "startMinute": SCHEDULE_MINUTES[start_minute],
        "endHour": end_hour,
        "endMinute": SCHEDULE_MINUTES[end_minute],
    }


def _window_name(value: str) -> str:
    day, start, end = value.split(",")
    return f"{day.title()[:3]} {start}\u2013{end}"


def _audience_plan(
    change: GoogleAdsTargetingChange,
    owner: _Owner,
    criteria: Mapping[str, LiveCriterion],
    names: Mapping[str, str],
) -> list[_Planned]:
    planned: list[_Planned] = []
    for removed in change.remove_audiences:
        value = audience_value(removed.kind, removed.key)
        planned.append(
            _Planned(
                edit=_criterion_change(owner, "remove", "audience", value, criteria),
                field="remove_audiences",
                item=value,
                setting="audiences",
                action="remove",
                name=names.get(value) or removed.name or value,
            )
        )
    for item in change.add_audiences:
        value = audience_value(item.kind, item.key)
        field, name_field, collection = AUDIENCE_FIELDS[item.kind]
        body = {field: {name_field: f"customers/{owner.customer_id}/{collection}/{item.key}"}}
        edit, action, previous = _bid_or_add(
            owner, "audience", value, body, item.bid_adjustment, criteria
        )
        planned.append(
            _Planned(
                edit=edit,
                field="add_audiences",
                item=value,
                setting="audiences",
                action=action,
                name=names.get(value) or item.name or value,
                bid_adjustment=item.bid_adjustment,
                previous_bid_adjustment=previous,
            )
        )
    return planned


def _demographic_plan(
    change: GoogleAdsTargetingChange, owner: _Owner, criteria: Mapping[str, LiveCriterion]
) -> list[_Planned]:
    """Excludes each value, or sets its adjustment, moving it between the two lists as needed.

    Google can't change a criterion's excluded flag, so a move is a removal and an add, sent
    together. An adjustment of 0 on an excluded value includes it again.
    """
    planned: list[_Planned] = []
    for target in change.demographics:
        value = demographic_value(target.dimension, target.value)
        included = criteria.get(criterion_key(owner.name, "demographic", value))
        excluded = criteria.get(criterion_key(owner.name, "excluded_demographic", value))
        body = {DEMOGRAPHIC_FIELDS[target.dimension]: {"type": target.value}}
        moving = included if target.excluded else excluded
        final: Edit | None
        if target.excluded:
            final = _criterion_change(
                owner, "add", "excluded_demographic", value, criteria, {"negative": True, **body}
            )
        elif included is not None:
            final = _bid_change(owner, included, _modifier(target.bid_adjustment or 0))
        elif target.bid_adjustment:
            final = _criterion_change(
                owner,
                "add",
                "demographic",
                value,
                criteria,
                {**body, BID_MODIFIER_PATH: _modifier(target.bid_adjustment)},
            )
        elif excluded is None:
            # Nothing is set and no adjustment is asked for, so there's nothing to send.
            final = CriterionChange(
                resource=owner.criterion,
                action="remove",
                key=criterion_key(owner.name, "demographic", value),
                owner=owner.name,
            )
        else:
            final = None
        previous = -100 if excluded else _percent(included.bid_modifier) if included else 0
        common = {
            "field": "demographics",
            "item": value,
            "setting": "demographics",
            "name": _demographic_name(target.dimension, target.value),
            "bid_adjustment": -100 if target.excluded else target.bid_adjustment,
            "previous_bid_adjustment": previous,
        }
        group = f"{owner.name}#{value}" if moving is not None and final is not None else None
        if moving is not None:
            kind: CriterionKind = "demographic" if target.excluded else "excluded_demographic"
            removal = _criterion_change(owner, "remove", kind, value, criteria)
            planned.append(
                _Planned(
                    edit=replace(removal, atomic_group=group),
                    action="remove" if final is not None else "set",
                    shown=final is None,
                    **common,
                )
            )
        if final is not None:
            planned.append(
                _Planned(edit=replace(final, atomic_group=group), action="set", **common)
            )
    return planned


_AGE_NAMES = {
    "AGE_RANGE_18_24": "18\u201324",
    "AGE_RANGE_25_34": "25\u201334",
    "AGE_RANGE_35_44": "35\u201344",
    "AGE_RANGE_45_54": "45\u201354",
    "AGE_RANGE_55_64": "55\u201364",
    "AGE_RANGE_65_UP": "65+",
}
_INCOME_NAMES = {
    "INCOME_RANGE_0_50": "Lower 50%",
    "INCOME_RANGE_50_60": "41\u201350%",
    "INCOME_RANGE_60_70": "31\u201340%",
    "INCOME_RANGE_70_80": "21\u201330%",
    "INCOME_RANGE_80_90": "11\u201320%",
    "INCOME_RANGE_90_UP": "Top 10%",
}
_DIMENSION_NAMES = {
    "AGE_RANGE": "Age",
    "GENDER": "Gender",
    "PARENTAL_STATUS": "Parental Status",
    "INCOME_RANGE": "Household Income",
}


def _demographic_name(dimension: str, value: str) -> str:
    """Names a value as Google Ads does, such as `Age 18-24` or `Household Income Top 10%`."""
    if value.endswith("UNDETERMINED"):
        shown = "Unknown"
    else:
        shown = _AGE_NAMES.get(value) or _INCOME_NAMES.get(value) or value.replace("_", " ").title()
    return f"{_DIMENSION_NAMES[dimension]} {shown}"


def _bidding_note(change: GoogleAdsTargetingChange, live: LiveTargeting | None) -> str | None:
    """Warns when the campaign's bidding ignores the adjustments the request sets."""
    if live is None:
        return None
    smart = live.ignores_smart_bidding_adjustments()
    devices = live.ignores_device_bids() and any(item.bid_adjustment for item in change.devices)
    demographics = smart and any(item.bid_adjustment for item in change.demographics)
    kinds = [
        kind
        for kind, ignored in (
            ("device", devices),
            ("time", smart and any(item.bid_adjustment for item in change.ad_schedule or ())),
            ("audience", smart and any(item.bid_adjustment for item in change.add_audiences)),
            ("demographic", demographics),
        )
        if ignored
    ]
    if not kinds:
        return None
    what = kinds[0] if len(kinds) == 1 else f"{', '.join(kinds[:-1])} and {kinds[-1]}"
    return _IGNORED_BIDS.format(what=f"{what} bid adjustments") + (
        _EXCLUDING_WORKS if devices or demographics else ""
    )


def _owner_problem(live: LiveTargeting | None, planned: Sequence[_Planned]) -> str | None:
    if live is None:
        return _MISSING
    if live.campaign_id is not None:
        return _AD_GROUP_REMOVED if "REMOVED" in {live.status, live.campaign_status} else None
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
    live: LiveTargeting | None,
    names: Mapping[str, Mapping[str, str]],
) -> str | None:
    if item.field == "add_languages":
        if live is not None and live.channel == "SEARCH":
            return _SEARCH_LANGUAGES
        if item.item not in names["languages"]:
            return _UNKNOWN_LANGUAGE
    if item.field in {"add_locations", "exclude_locations"} and item.item not in names["locations"]:
        return _UNKNOWN_LOCATION
    if item.field == "add_audiences" and item.item not in names["audiences"]:
        return _UNKNOWN_AUDIENCE
    return None


def _with_refusals(
    planned: Sequence[_Planned],
    live: LiveTargeting | None,
    names: Mapping[str, Mapping[str, str]],
    shown_problem: str | None = None,
) -> tuple[list[_Planned], str | None]:
    """Marks what mustn't be sent, and returns the problem that stops the whole entry.

    An add that can't be sent doesn't count as a location the campaign keeps.
    """
    sendable = [item for item in planned if _item_problem(item, live, names) is None]
    problem = shown_problem or _owner_problem(live, sendable)
    refused: list[_Planned] = []
    for item in planned:
        reason = problem or _item_problem(item, live, names)
        refused.append(replace(item, edit=replace(item.edit, refused=reason)) if reason else item)
    return refused, problem


def _edits(planned: Iterable[_Planned]) -> list[Edit]:
    """Each edit once; the location setting and audience mode share one update."""
    edits: dict[str, Edit] = {}
    for item in planned:
        edits.setdefault(item.edit.key, item.edit)
    return list(edits.values())


async def _read_names(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    changes: Iterable[GoogleAdsTargetingChange],
    live: Mapping[str, LiveTargeting],
) -> dict[str, dict[str, str]]:
    """Reads Google's names for what the request names and what each entry shows."""
    changes = list(changes)
    customer, login = entry.external_id, login_customer_id(entry)
    requested = [
        item.key
        for change in changes
        for items in (change.add_locations, change.exclude_locations, change.remove_locations)
        for item in items
    ]
    shown = [key for targeting in live.values() for key in _shown_location_keys(targeting)]
    locations = (
        await read_locations(
            client, customer_id=customer, login_customer_id=login, keys=[*requested, *shown]
        )
        if requested or shown
        else {}
    )
    languages = (
        await read_languages(client, customer_id=customer, login_customer_id=login)
        if any(change.campaign is not None for change in changes)
        else []
    )
    audience_keys: dict[str, list[str]] = defaultdict(list)
    for change in changes:
        for item in (*change.add_audiences, *change.remove_audiences):
            audience_keys[item.kind].append(item.key)
    for targeting in live.values():
        for criterion in targeting.criteria.values():
            if criterion.kind == "audience":
                kind, key = criterion.value.split(":")
                audience_keys[kind].append(key)
    audiences = (
        await read_audiences(
            client, customer_id=customer, login_customer_id=login, keys=audience_keys
        )
        if audience_keys
        else {}
    )
    return {
        "locations": {key: option.name for key, option in locations.items()},
        "languages": {option.key: option.name for option in languages},
        "audiences": {
            audience_value(kind, key): option.name for (kind, key), option in audiences.items()
        },
        "eu_locations": {
            key: option.name for key, option in locations.items() if option.eu_political_declaration
        },
    }


def _shown_location_keys(targeting: LiveTargeting) -> list[str]:
    places = [
        criterion.value
        for criterion in targeting.criteria.values()
        if criterion.kind in {"location", "excluded_location"}
    ]
    return places[:_MAX_SHOWN]


async def _read_live(
    client: GoogleAdsClient, entry: ResolvedContextEntry, owners: Iterable[str]
) -> dict[str, LiveTargeting]:
    """Reads each campaign and ad group, by resource name."""
    campaign_ids: list[str] = []
    ad_group_ids: list[str] = []
    for owner in owners:
        _customers, _customer, collection, owner_id = owner.split("/")
        (campaign_ids if collection == "campaigns" else ad_group_ids).append(owner_id)
    return await read_targeting(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=campaign_ids,
        ad_group_ids=ad_group_ids,
        types=_TYPES,
    )


def _reader(
    client: GoogleAdsClient, entry: ResolvedContextEntry, owners: Sequence[str]
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        live = await _read_live(client, entry, owners)
        return {key: value for item in live.values() for key, value in item.values().items()}

    return read


def _live_settings(live: LiveTargeting | None) -> dict[str, Any]:
    if live is None:
        return {}
    return {
        _SETTING_PATH: live.location_setting,
        RESTRICTIONS_PATH: [dict(item) for item in live.restrictions],
        EU_POLITICAL_PATH: live.eu_political,
    }


async def google_ads_update_targeting(
    ctx: RunContext[RuntimeDeps],
    changes: Annotated[
        list[GoogleAdsTargetingChange],
        Field(
            min_length=1,
            max_length=MAX_TARGETING_CHANGES,
            description="One entry per campaign or ad group, with only what changes.",
        ),
    ],
) -> dict[str, Any]:
    request = validated_request(GoogleAdsUpdateTargetingRequest, {"changes": changes})
    display = approved_display_args(ctx).get("_checks")
    shown: Mapping[str, Any] = display if isinstance(display, Mapping) else {}

    async def operation(entry: ResolvedContextEntry, selected: Sequence[Any]) -> Any:
        chosen = {id(reference) for reference in selected}
        account_changes = [c for c in request.changes if id(c.reference) in chosen]
        planned: dict[str, list[_Planned]] = {}
        parents: dict[str, dict[str, str | None]] = {}

        async def plan(client: GoogleAdsClient) -> EditPlan:
            # Accounts change between the check and the send, so read them again as approved.
            live = await _read_live(client, entry, [change.owner for change in account_changes])
            for change in account_changes:
                targeting = live.get(change.owner)
                planned[change.owner] = _approved_plan(change, shown, targeting)
                parents[change.owner] = _parent(change, targeting)
            edits = _edits(item for items in planned.values() for item in items)
            return edits, _pending_detail(entry, planned)

        async def result(client: GoogleAdsClient, applied: EditResult) -> dict[str, Any]:
            return _result(entry, planned, parents, applied)

        return await run_approved_edits(
            ctx,
            entry,
            tool_name="google_ads_update_targeting",
            operation=_OPERATION,
            family="targeting",
            plan=plan,
            read=lambda client: _reader(client, entry, list(planned)),
            result=result,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[change.reference for change in request.changes],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _parent(change: GoogleAdsTargetingChange, live: LiveTargeting | None) -> dict[str, str | None]:
    """The campaign, and the ad group when there is one, that a result row names."""
    if change.ad_group is not None:
        return {
            "campaign_id": change.ad_group.campaign_id,
            "campaign_name": (live.campaign_name if live else None) or change.ad_group.campaign_id,
            "ad_group_id": change.ad_group.ad_group_id,
            "ad_group_name": live.name if live else change.ad_group.label,
        }
    campaign = change.reference
    return {
        "campaign_id": campaign.provider_entity_id,
        "campaign_name": live.name if live else campaign.label,
        "ad_group_id": None,
        "ad_group_name": None,
    }


def _approved_plan(
    change: GoogleAdsTargetingChange,
    shown: Mapping[str, Any],
    live: LiveTargeting | None,
) -> list[_Planned]:
    """Plans against what the approver saw, so `apply_edits` refuses anything changed since."""
    checks = shown.get("entries")
    check = checks.get(change.owner) if isinstance(checks, Mapping) else None
    names = shown.get("names")
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or not isinstance(names, Mapping)
    ):
        planned = _plan(change, {}, {}, _NO_NAMES)
        return [replace(item, edit=replace(item.edit, refused=NOT_SHOWN)) for item in planned]
    criteria = {
        key: LiveCriterion(**values) for key, values in (check.get("criteria") or {}).items()
    }
    settings = {
        _SETTING_PATH: check.get("location_setting"),
        RESTRICTIONS_PATH: check.get("restrictions") or [],
        EU_POLITICAL_PATH: check.get("eu_political"),
    }
    names = {**_NO_NAMES, **names}
    planned = _plan(change, criteria, settings, names)
    # Google's answers aren't asked for again, so a problem they caused still stands.
    shown_problem = check.get("problem")
    refused = _with_refusals(
        planned, live, names, shown_problem if isinstance(shown_problem, str) else None
    )[0]
    # The schedule is approved as the whole week, so a window added since makes it stale.
    if _windows(criteria) == _windows(live.criteria if live else {}):
        return refused
    return [
        replace(item, edit=replace(item.edit, refused=item.edit.refused or STALE_MESSAGE))
        if item.field == "ad_schedule"
        else item
        for item in refused
    ]


def _windows(criteria: Mapping[str, LiveCriterion]) -> set[str]:
    return {criterion.value for criterion in criteria.values() if criterion.kind == "schedule"}


def _pending_detail(
    entry: ResolvedContextEntry, planned: Mapping[str, Sequence[_Planned]]
) -> PendingIntegrationOperationDetail:
    """Records each change by key; names of places and audiences stay out of the audit record."""
    groups: dict[tuple[str, str], list[IntegrationOperationIntent]] = defaultdict(list)
    recorded: set[str] = set()
    for items in planned.values():
        for item in items:
            # One intent per edit, which the ledger matches on.
            if item.edit.key in recorded:
                continue
            recorded.add(item.edit.key)
            groups[item.setting, item.action].append(
                IntegrationOperationIntent(fields={"object": item.edit.key})
            )
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"{setting}:{action}",
                action=action,
                entity_type="google_ads_targeting",
                items=items,
            )
            for (setting, action), items in groups.items()
        ],
    )


def _already_at(item: _Planned) -> bool:
    """Whether a setting that shares its update with another is already at its value."""
    edit = item.edit
    return (
        isinstance(edit, FieldChange)
        and item.path is not None
        and edit.before.get(item.path) == edit.requested.get(item.path)
    )


def _result(
    entry: ResolvedContextEntry,
    planned: Mapping[str, Sequence[_Planned]],
    owners: Mapping[str, Mapping[str, str | None]],
    result: EditResult,
) -> dict[str, Any]:
    ledger = {dict(parent.identity)["object"]: parent for parent in result.ledger.parents}
    rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for owner, items in planned.items():
        for item in items:
            if not item.shown:
                continue
            parent = ledger[item.edit.key]
            effect = parent.effects[0] if parent.effects else None
            outcome = (
                "already_set"
                if parent.decision == "skipped" or (_already_at(item) and item.edit.refused is None)
                else _OUTCOMES[effect.outcome if effect else "unverified"]
            )
            row = rows.setdefault(
                (owner, item.setting, item.action, outcome),
                {
                    **owners[owner],
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
    """Adds each account's facts, what each entry targets now, and Google's dry run."""
    request = GoogleAdsUpdateTargetingRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsTargetingChange]] = defaultdict(list)
    for change in request.changes:
        by_account[change.reference.customer_id].append(change)
    entries = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    names: dict[str, dict[str, str]] = {kind: {} for kind in _NO_NAMES}
    for customer_id, changes in by_account.items():
        account_checks, account_names = await _account_checks(
            deps, entries.get(customer_id), changes
        )
        checks.update(account_checks)
        for kind, values in account_names.items():
            names[kind].update(values)
    accounts = approval_accounts(entries[item] for item in by_account if item in entries)
    return {
        **args,
        "_accounts": accounts,
        "_checks": {"entries": checks, "names": names},
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
        live = await _read_live(client, entry, [change.owner for change in changes])
        names = await _read_names(client, entry, changes, live)
        plans = [_checked_plan(change, live, names) for change in changes]
        edits = _edits(item for planned, _problem in plans for item in planned)
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
        return {change.owner: {"unavailable": True} for change in changes}, _NO_NAMES
    results = {edit.key: edit for edit in prepared}
    return (
        {
            change.owner: _check(change, live.get(change.owner), *plan, results, names)
            for change, plan in zip(changes, plans, strict=True)
        },
        names,
    )


def _checked_plan(
    change: GoogleAdsTargetingChange,
    live: Mapping[str, LiveTargeting],
    names: Mapping[str, Mapping[str, str]],
) -> tuple[list[_Planned], str | None]:
    targeting = live.get(change.owner)
    planned = _plan(
        change, targeting.criteria if targeting else {}, _live_settings(targeting), names
    )
    return _with_refusals(planned, targeting, names)


def _check(
    change: GoogleAdsTargetingChange,
    live: LiveTargeting | None,
    planned: Sequence[_Planned],
    problem: str | None,
    results: Mapping[str, Edit],
    names: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Builds the card's view of one entry, and the live values approval plans against."""
    # An add Google rejected won't happen, so removals alongside it could leave no location.
    problem = problem or _owner_problem(
        live, [item for item in planned if results[item.edit.key].refused is None]
    )
    item_problems, already = _item_answers(planned, problem, results)
    criteria = live.criteria if live else {}
    touched = {key: asdict(criteria[key]) for item in planned if (key := item.edit.key) in criteria}
    by_resource = {criterion.resource_name: key for key, criterion in criteria.items()}
    for item in planned:
        key = by_resource.get(item.edit.key)
        if key is not None:
            touched[key] = asdict(criteria[key])
    return {
        "unavailable": False,
        "level": "ad_group" if change.ad_group is not None else "campaign",
        "name": live.name if live else change.reference.label,
        "campaign_name": live.campaign_name if live else None,
        "channel": live.channel if live else None,
        "status": live.status if live else None,
        "problem": problem,
        "location_setting": live.location_setting if live else None,
        "restrictions": [dict(item) for item in live.restrictions] if live else [],
        "eu_political": live.eu_political if live else None,
        # True when the card must ask whether the ads are EU political ads.
        "eu_political_question": any(item.field == _EU_POLITICAL for item in planned),
        "audience_mode": live.audience_mode() if live else None,
        **_shown_criteria(criteria, names),
        "note": _bidding_note(change, live),
        "item_problems": [
            {"field": field, "key": key, "message": message}
            for (field, key), message in item_problems.items()
        ],
        "already_set": already,
        # What approval plans against; only criteria this request touches.
        "criteria": touched,
    }


def _item_answers(
    planned: Sequence[_Planned], problem: str | None, results: Mapping[str, Edit]
) -> tuple[dict[tuple[str, str], str], list[dict[str, str]]]:
    """Google's answer for each item: why it can't be sent, or that it's already set."""
    item_problems: dict[tuple[str, str], str] = {}
    already: list[dict[str, str]] = []
    schedule = [results[item.edit.key] for item in planned if item.field == "ad_schedule"]
    for item in planned:
        edit = results[item.edit.key]
        if edit.refused and edit.refused != problem:
            message = edit.refused
            if item.edit.refused is None:
                message = f"Google says: {message}"
            item_problems.setdefault((item.field, item.item), message)
        unchanged = edit.unchanged or _already_at(replace(item, edit=edit))
        # The schedule is one change, already set only when none of its windows change.
        if edit.refused is None and unchanged and item.shown and item.field != "ad_schedule":
            already.append({"field": item.field, "key": item.item})
    if schedule and all(edit.refused is None and edit.unchanged for edit in schedule):
        already.append({"field": "ad_schedule", "key": "ad_schedule"})
    return item_problems, already


def _shown_criteria(
    criteria: Mapping[str, LiveCriterion], names: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    """What the entry targets now, by setting, as the card lists it."""
    places = [c for c in criteria.values() if c.kind in {"location", "excluded_location"}]
    return {
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
        "devices": [
            {"device": c.value, "bid_adjustment": _percent(c.bid_modifier)}
            for c in criteria.values()
            if c.kind == "device"
        ],
        "ad_schedule": [
            {
                "day": day,
                "start": start,
                "end": end,
                "bid_adjustment": _percent(c.bid_modifier),
            }
            for c in criteria.values()
            if c.kind == "schedule"
            for day, start, end in [c.value.split(",")]
        ],
        "audiences": [
            {
                "kind": kind,
                "key": key,
                "name": names["audiences"].get(c.value, c.value),
                "bid_adjustment": _percent(c.bid_modifier),
            }
            for c in criteria.values()
            if c.kind == "audience"
            for kind, key in [c.value.split(":")]
        ][:_MAX_SHOWN],
        "demographics": [
            {
                "dimension": dimension,
                "value": value,
                "excluded": c.kind == "excluded_demographic",
                "bid_adjustment": _percent(c.bid_modifier),
            }
            for c in criteria.values()
            if c.kind in {"demographic", "excluded_demographic"}
            for dimension, value in [c.value.split(":")]
        ],
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_targeting",
    function=google_ads_update_targeting,
    description=(
        "Change where, when, on which devices, and to whom existing Google Ads campaigns and "
        "ad groups show ads, up to 20 entries per call, in one approval. Each entry names one "
        "campaign or one ad group and only what changes, as additions and removals. Ad group "
        "entries take add_audiences, remove_audiences, audience_mode, and demographics only; "
        "everything else is set on the campaign. "
        "add_locations, exclude_locations, and remove_locations take location keys from "
        "google_ads_search_targeting; add_locations can set bid_adjustment as a percent from "
        "-90 to 900, and naming a location already targeted changes its adjustment. Excluding "
        "an included location, or adding an excluded one, moves it. add_radius takes latitude, "
        "longitude, radius, and units (MILES or KILOMETERS), with an optional label and "
        "bid_adjustment; remove_radius takes criterion IDs from google_ads_run_report. "
        "location_setting is PRESENCE_OR_INTEREST (people in, or showing interest in, a "
        "location) or PRESENCE (people in, or regularly in, a location). add_languages and "
        "remove_languages take language keys. Search campaigns can't add languages because "
        "Google matches each ad's language; a language left on one from before can be removed. "
        "A change that would leave a campaign with no location is refused, because its ads "
        "could then show anywhere. contains_eu_political_advertising, on a campaign entry, is "
        "true only when the user says the ads are political and aimed at the EU; Google needs "
        "the answer when a campaign that hasn't given it adds an EU location or a radius, and "
        "the card then asks the user. devices sets MOBILE, DESKTOP, or TABLET to a bid_adjustment "
        "percent (0 clears it) or excluded true. ad_schedule is the campaign's whole weekly "
        "schedule after the change: windows of day (MONDAY to SUNDAY), start and end as HH:MM "
        "in quarter hours in the account's time zone (end may be 24:00), and an optional "
        "bid_adjustment, without which the window has no adjustment; at most 6 windows a day, "
        "none overlapping. Windows left out are removed, and clear_ad_schedule true removes "
        "every window so ads show at any time. add_audiences and remove_audiences take kind "
        "and key from google_ads_search_targeting with kind audience; add_audiences can set "
        "bid_adjustment, and naming an audience already added changes its adjustment. "
        "audience_mode OBSERVATION only adjusts bids for the audiences, so who sees the ads "
        "doesn't change; TARGETING shows ads only to people in them. Set audience_mode only "
        "when audiences stay on the entry, never with removals alone. Keep audiences at one "
        "level per campaign: on the campaign, or on its ad groups. demographics sets a "
        "dimension (AGE_RANGE, GENDER, PARENTAL_STATUS, INCOME_RANGE) and Google's value, such "
        "as AGE_RANGE_18_24, FEMALE, NOT_A_PARENT, or INCOME_RANGE_90_UP, to a bid_adjustment "
        "percent (0 clears it, and includes an excluded value again) or excluded true. On "
        "Search, set demographics on ad groups. Target ROAS, Maximize Conversion Value, and "
        "Maximize Conversions without a target CPA ignore device adjustments other than "
        "excluding; Smart Bidding ignores time, audience, and demographic adjustments. Check "
        "campaign.bidding_strategy_type with google_ads_run_report first and only propose "
        "adjustments that bidding uses. Each result reports what Google Ads shows after the "
        "change."
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
                # The first kind authorises a review; the card adds the rest from searches.
                entity_kinds=(
                    "google_ads_campaign",
                    "google_ads_ad_group",
                    "google_ads_location",
                    "google_ads_language",
                    "google_ads_audience",
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
