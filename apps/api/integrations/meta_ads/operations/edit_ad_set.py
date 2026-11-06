# apps/api/integrations/meta_ads/operations/edit_ad_set.py

"""Rules and the Meta request body for changing the settings of one existing ad set."""

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from pydantic_ai import ModelRetry

from ..goals import GOALS, MetaAdsGoal, fits_destination, goal_for
from ..money import amount_to_minor
from ..tools.schemas.ad_set_edits import MetaAdsAdSetEdit, MetaAdsAdSetSetting
from ..tools.schemas.budgets import BID_STRATEGIES
from ..tools.schemas.delivery import WEEKDAYS, MetaAdsAdSchedule, canonical
from ..tools.schemas.objects import CLOSED_STATUSES, MetaAdsObject
from ..tools.utils.validation import absolute_date
from .create_ad_set import (
    BID_AMOUNT_STRATEGIES,
    LEGACY_ADVANTAGE_TYPES,
    bid_problem,
    includes_eu,
    spend_control_problems,
    store_for,
)
from .list_objects import NO_SPEND_CAP

MONEY_SETTINGS = frozenset(
    {"bid_amount", "min_daily_spend", "max_daily_spend", "min_lifetime_spend", "max_lifetime_spend"}
)
BID_SETTINGS = frozenset({"bid_strategy", "bid_amount", "min_roas"})
# Promoted object settings, by the goal asset each belongs to.
_ASSET_SETTINGS = {
    "page": "page",
    "pixel": "pixel",
    "conversion_event": "pixel",
    "custom_conversion_id": "pixel",
    "app": "app",
    "app_store": "app",
}
PROMOTED_SETTINGS = frozenset(_ASSET_SETTINGS)
# Settings whose change Meta counts as significant, so learning starts again.
LEARNING_SETTINGS = BID_SETTINGS | PROMOTED_SETTINGS | {"goal", "attribution"}
# Goals that optimise for conversions, the only ones an attribution setting applies to.
_CONVERSION_GOALS = frozenset({"OFFSITE_CONVERSIONS", "VALUE", "APP_INSTALLS"})
# Goals Meta lets cap how often one person sees the ads.
_FREQUENCY_GOALS = frozenset({"REACH", "THRUPLAY"})
SPEND_SETTINGS = (
    ("min_daily_spend", "daily_min_spend_target"),
    ("max_daily_spend", "daily_spend_cap"),
    ("min_lifetime_spend", "lifetime_min_spend_target"),
    ("max_lifetime_spend", "lifetime_spend_cap"),
)
LEGACY_ADVANTAGE = (
    "Meta no longer allows changes to this campaign through its API; copy it in Ads Manager "
    "to a current campaign."
)
_STRATEGY_KEYS = {meta: key for key, meta in BID_STRATEGIES.items()}


def ad_set_values(item: MetaAdsObject, zone: ZoneInfo) -> dict[str, str | None]:
    """Reads each setting the way an edit names it; None means not set."""
    promoted = item.promoted_object
    return {
        "name": item.name,
        "start_date": _local_date(item.start_time, zone),
        "end_date": _local_date(item.end_time, zone),
        "bid_strategy": _STRATEGY_KEYS.get(item.bid_strategy or "", item.bid_strategy),
        "bid_amount": item.bid_amount,
        "min_roas": item.min_roas,
        "min_daily_spend": item.min_daily_spend,
        "max_daily_spend": item.max_daily_spend,
        "min_lifetime_spend": item.min_lifetime_spend,
        "max_lifetime_spend": item.max_lifetime_spend,
        "eu_payer": item.eu_payer,
        "eu_beneficiary": item.eu_beneficiary,
        # A goal outside Praxis's table shows as Meta's own name for it.
        "goal": goal_for(item.objective, item.optimization_goal, item.destination_type)
        or item.optimization_goal,
        "pixel": promoted.pixel_id if promoted else None,
        "conversion_event": promoted.custom_event_type
        if promoted and promoted.pixel_id and not promoted.custom_conversion_id
        else None,
        "custom_conversion_id": promoted.custom_conversion_id if promoted else None,
        "page": promoted.page_id if promoted else None,
        "app": promoted.application_id if promoted else None,
        "app_store": store_for(promoted.object_store_url) if promoted else None,
        "attribution": canonical(item.attribution) if item.attribution else None,
        "frequency_cap": canonical(item.frequency_cap) if item.frequency_cap else None,
        "ad_schedule": canonical(item.ad_schedule) if item.ad_schedule else None,
    }


def requested_values(edit: MetaAdsAdSetEdit) -> dict[MetaAdsAdSetSetting, str | None]:
    """The values the edit asks for, as `ad_set_values` reads them; removing asks for None."""
    return {key: _requested(getattr(edit, key)) for key in edit.settings}


def _requested(value: Any) -> str | None:
    if value in ("remove", "none"):
        return None
    if isinstance(value, BaseModel) and hasattr(value, "provider_entity_id"):
        return value.provider_entity_id
    if isinstance(value, BaseModel):
        return canonical(value)
    return value


def edit_problems(
    edit: MetaAdsAdSetEdit,
    ad_set: MetaAdsObject,
    campaign: MetaAdsObject,
    *,
    currency: str,
    zone: ZoneInfo,
    today: date,
) -> list[str]:
    """Lists the Meta rules this edit breaks for the ad set as it is now."""
    if campaign.smart_promotion_type in LEGACY_ADVANTAGE_TYPES:
        return [LEGACY_ADVANTAGE]
    if ad_set.status in CLOSED_STATUSES and set(edit.settings) - {"name"}:
        return ["This ad set is archived or deleted, so only its name can change."]
    problems = _precision_problems(edit, currency)
    problems.extend(_bid_problems(edit, ad_set, campaign))
    problems.extend(_spend_problems(edit, ad_set))
    problems.extend(_schedule_problems(edit, ad_set, zone, today))
    if (edit.eu_payer or edit.eu_beneficiary) and not includes_eu(ad_set.countries or ()):
        problems.append(
            "This ad set doesn't reach anyone in the EU, so leave eu_payer and eu_beneficiary out."
        )
    problems.extend(_goal_problems(edit, ad_set))
    problems.extend(_delivery_problems(edit, ad_set))
    return problems


def _goal_problems(edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject) -> list[str]:
    if edit.goal is not None:
        row = GOALS[edit.goal]
        if row.objective != ad_set.objective:
            return [f"The goal {edit.goal} doesn't suit this ad set's campaign objective."]
        if not fits_destination(row, ad_set.destination_type):
            return [
                f"The goal {edit.goal} sends people somewhere else, and Meta doesn't let an ad "
                "set change where it sends people. Create a new ad set with this goal instead."
            ]
    promoted = PROMOTED_SETTINGS.intersection(edit.settings)
    if not promoted and edit.goal is None:
        return []
    goal = after_goal(edit, ad_set)
    if goal is None:
        return ["This ad set's goal can't be changed here. Change it in Ads Manager."]
    asset = GOALS[goal].asset
    if unused := sorted(key for key in promoted if _ASSET_SETTINGS[key] != asset):
        return [f"The goal {goal} doesn't use {unused[0]}, so leave it out."]
    after = after_promoted(edit, ad_set, store_url=None)
    if asset == "pixel" and not (
        after.get("custom_conversion_id") or after.get("custom_event_type")
    ):
        return ["Set conversion_event or custom_conversion_id for the pixel."]
    needed = {"page": "page_id", "pixel": "pixel_id", "app": "application_id"}
    if asset is not None and not after.get(needed[asset]):
        return [f"The goal {goal} needs a {asset}."]
    return []


def after_goal(edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject) -> MetaAdsGoal | None:
    """The goal the ad set has once the edit applies; None for a goal outside the table."""
    return edit.goal or goal_for(
        ad_set.objective, ad_set.optimization_goal, ad_set.destination_type
    )


def after_promoted(
    edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject, *, store_url: str | None
) -> dict[str, str]:
    """The promoted object once the edit applies: the goal's asset, with the edit's changes.

    `store_url` is the app's store page for a new app or store, read at preparation.
    """
    current = ad_set.promoted_object
    goal = after_goal(edit, ad_set)
    asset = GOALS[goal].asset if goal else None
    if asset == "page":
        page = edit.page.page_id if edit.page else current.page_id if current else None
        return {"page_id": page} if page else {}
    if asset == "app":
        app = edit.app.application_id if edit.app else current.application_id if current else None
        url = store_url if edit.app else current.object_store_url if current else None
        if app is None:
            return {}
        return {"application_id": app, **({"object_store_url": url} if url else {})}
    if asset != "pixel":
        return {}
    pixel = edit.pixel.pixel_id if edit.pixel else current.pixel_id if current else None
    if pixel is None:
        return {}
    conversion = edit.custom_conversion_id
    if conversion is None and edit.conversion_event is None and current:
        conversion = current.custom_conversion_id
    if conversion:
        return {"pixel_id": pixel, "custom_conversion_id": conversion}
    event = edit.conversion_event or (current.custom_event_type if current else None)
    return {"pixel_id": pixel, "custom_event_type": event} if event else {"pixel_id": pixel}


def _delivery_problems(edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject) -> list[str]:
    problems: list[str] = []
    optimisation = GOALS[edit.goal].optimization_goal if edit.goal else ad_set.optimization_goal
    if (attribution := edit.attribution) is not None:
        if optimisation not in _CONVERSION_GOALS:
            problems.append("Only website conversion and app install goals take attribution.")
        elif (
            attribution.click_days not in (1, 7)
            or attribution.view_days not in (0, 1)
            or attribution.engaged_view_days not in (0, 1)
        ):
            problems.append(
                "Set click_days to 1 or 7, and view_days and engaged_view_days to 0 or 1."
            )
    if edit.frequency_cap not in (None, "remove") and optimisation not in _FREQUENCY_GOALS:
        problems.append("Only reach and ThruPlay goals take a frequency cap.")
    if edit.ad_schedule not in (None, "remove") and not lifetime_budget(ad_set):
        problems.append("Ad scheduling needs a lifetime budget.")
    return problems


def _precision_problems(edit: MetaAdsAdSetEdit, currency: str) -> list[str]:
    for key in MONEY_SETTINGS.intersection(edit.settings):
        value = getattr(edit, key)
        if value == "remove":
            continue
        try:
            amount_to_minor(value, currency)
        except ValueError:
            return [f"Use whole {currency} amounts for {key}."]
    return []


def campaign_holds_bids(campaign: MetaAdsObject) -> bool:
    """With a campaign budget, or a strategy set on the campaign, its ad sets follow it."""
    return campaign.budget is not None or campaign.bid_strategy is not None


def _bid_problems(
    edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject, campaign: MetaAdsObject
) -> list[str]:
    if edit.bid_strategy is not None:
        if campaign_holds_bids(campaign):
            return [
                (
                    "The campaign sets the bid strategy for its ad sets, so change it with "
                    "meta_ads_update_campaigns."
                )
            ]
        problem = bid_problem(
            BID_STRATEGIES[edit.bid_strategy],
            bid_amount=edit.bid_amount is not None,
            min_roas=edit.min_roas is not None,
        )
        return [problem] if problem else []
    strategy = ad_set.bid_strategy or campaign.bid_strategy
    if edit.bid_amount is not None and strategy not in BID_AMOUNT_STRATEGIES:
        return [
            "This ad set's bid strategy doesn't take a bid_amount. Set bid_strategy to bid_cap "
            "or cost_per_result_goal with it."
        ]
    if edit.min_roas is not None and strategy != "LOWEST_COST_WITH_MIN_ROAS":
        return ["Only a roas_goal bid strategy takes min_roas."]
    return []


def _spend_problems(edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject) -> list[str]:
    if not any(getattr(edit, key) is not None for key, _field in SPEND_SETTINGS):
        return []
    budget = ad_set.budget
    period = budget.period if budget is not None and budget.kind == "campaign" else None
    after = {
        key: value
        for key, _field in SPEND_SETTINGS
        if (value := _after(getattr(edit, key), getattr(ad_set, key))) is not None
    }
    return spend_control_problems(
        period,
        min_daily=after.get("min_daily_spend"),
        max_daily=after.get("max_daily_spend"),
        min_lifetime=after.get("min_lifetime_spend"),
        max_lifetime=after.get("max_lifetime_spend"),
    )


def _after(requested: str | None, current: str | None) -> str | None:
    if requested is None:
        return current
    return None if requested == "remove" else requested


def lifetime_budget(ad_set: MetaAdsObject) -> bool:
    budget = ad_set.budget
    return budget is not None and "lifetime" in (budget.kind, budget.period)


def _schedule_problems(
    edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject, zone: ZoneInfo, today: date
) -> list[str]:
    if edit.start_date is None and edit.end_date is None:
        return []
    try:
        start, end = edit_dates(edit, ad_set, zone)
    except ModelRetry as exc:
        return [str(exc)]
    if edit.start_date is not None and start is not None and start < today:
        return [f"Set start_date to {today.isoformat()} or later."]
    if edit.end_date == "none":
        if lifetime_budget(ad_set):
            return ["A lifetime budget needs an end date, so keep end_date."]
        return []
    if end is not None and edit.end_date is not None and end < today:
        return [f"Set end_date to {today.isoformat()} or later."]
    if end is not None and start is not None and end < start:
        return ["Set end_date on or after the start date."]
    return []


def edit_dates(
    edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject, zone: ZoneInfo
) -> tuple[date | None, date | None]:
    """Returns the ad set's start and end dates after the edit, in the account's time zone.

    Raises:
        ModelRetry: For a date that isn't in YYYY-MM-DD format.
    """
    current = ad_set_values(ad_set, zone)
    start_text = edit.start_date or current["start_date"]
    end_text = None if edit.end_date == "none" else edit.end_date or current["end_date"]
    start = absolute_date(start_text, "start_date") if start_text else None
    end = absolute_date(end_text, "end_date") if end_text else None
    return start, end


def edit_body(
    edit: MetaAdsAdSetEdit,
    ad_set: MetaAdsObject,
    *,
    currency: str,
    zone: ZoneInfo,
    now: datetime,
    store_url: str | None = None,
) -> dict[str, str]:
    """Builds the update Meta receives: money in minor units and times in the account zone.

    `store_url` is the store page for a new app or store, read at preparation.
    """
    body: dict[str, str] = {}
    if edit.name is not None:
        body["name"] = edit.name
    if edit.start_date is not None:
        start = date.fromisoformat(edit.start_date)
        local_now = now.astimezone(zone)
        # A start today begins now, because midnight has already passed by Meta's clock.
        body["start_time"] = (
            local_now.replace(microsecond=0).isoformat()
            if start == local_now.date()
            else datetime.combine(start, time.min, tzinfo=zone).isoformat()
        )
    if edit.end_date is not None:
        body["end_time"] = (
            "0"
            if edit.end_date == "none"
            else datetime.combine(
                date.fromisoformat(edit.end_date), time(23, 59, 59), tzinfo=zone
            ).isoformat()
        )
    if edit.bid_strategy is not None:
        body["bid_strategy"] = BID_STRATEGIES[edit.bid_strategy]
    if edit.bid_amount is not None:
        body["bid_amount"] = str(amount_to_minor(edit.bid_amount, currency))
    if edit.min_roas is not None:
        floor = int(Decimal(edit.min_roas) * 10_000)
        body["bid_constraints"] = json.dumps({"roas_average_floor": floor})
    for key, field in SPEND_SETTINGS:
        if (value := getattr(edit, key)) is not None:
            minor = NO_SPEND_CAP if value == "remove" else amount_to_minor(value, currency)
            body[field] = str(minor)
    if edit.eu_payer is not None:
        body["dsa_payor"] = edit.eu_payer
    if edit.eu_beneficiary is not None:
        body["dsa_beneficiary"] = edit.eu_beneficiary
    body.update(_delivery_body(edit, ad_set, store_url))
    return body


def _delivery_body(
    edit: MetaAdsAdSetEdit, ad_set: MetaAdsObject, store_url: str | None
) -> dict[str, str]:
    body: dict[str, str] = {}
    if edit.goal is not None:
        # Only link clicks can bill on clicks, so a new goal bills on impressions.
        body.update(
            optimization_goal=GOALS[edit.goal].optimization_goal, billing_event="IMPRESSIONS"
        )
    if PROMOTED_SETTINGS.intersection(edit.settings):
        body["promoted_object"] = json.dumps(after_promoted(edit, ad_set, store_url=store_url))
    if (attribution := edit.attribution) is not None:
        spec = [{"event_type": "CLICK_THROUGH", "window_days": attribution.click_days}]
        for event, days in (
            ("VIEW_THROUGH", attribution.view_days),
            ("ENGAGED_VIDEO_VIEW", attribution.engaged_view_days),
        ):
            if days:
                spec.append({"event_type": event, "window_days": days})
        body["attribution_spec"] = json.dumps(spec)
    if (cap := edit.frequency_cap) is not None:
        specs = (
            []
            if cap == "remove"
            else [
                {
                    "event": "IMPRESSIONS",
                    "interval_days": cap.every_days,
                    "max_frequency": cap.max_impressions,
                }
            ]
        )
        body["frequency_control_specs"] = json.dumps(specs)
    if (schedule := edit.ad_schedule) is not None:
        body.update(_schedule_body(schedule))
    return body


def _schedule_body(schedule: MetaAdsAdSchedule | Literal["remove"]) -> dict[str, str]:
    if not isinstance(schedule, MetaAdsAdSchedule):
        return {"pacing_type": json.dumps(["standard"]), "adset_schedule": "[]"}
    zone = "USER" if schedule.time_zone == "viewer" else "ADVERTISER"
    entries = [
        {
            "start_minute": window.start_hour * 60,
            "end_minute": window.end_hour * 60,
            "days": sorted(WEEKDAYS.index(day) for day in window.days),
            "timezone_type": zone,
        }
        for window in schedule.windows
    ]
    return {"pacing_type": json.dumps(["day_parting"]), "adset_schedule": json.dumps(entries)}


def evidence_values(
    values: dict[str, str | None], keys: tuple[str, ...], currency: str
) -> dict[str, str | None]:
    """Records money in minor units, so the audit trail matches what Meta receives."""
    return {
        key: str(amount_to_minor(values[key], currency))
        if key in MONEY_SETTINGS and values.get(key) is not None
        else values.get(key)
        for key in keys
    }


def _local_date(value: str | None, zone: ZoneInfo) -> str | None:
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(zone).date().isoformat()
