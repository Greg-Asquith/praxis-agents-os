# apps/api/integrations/meta_ads/operations/edit_ad_set.py

"""Rules and the Meta request body for changing the settings of one existing ad set."""

import json
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic_ai import ModelRetry

from ..money import amount_to_minor
from ..tools.schemas.ad_set_edits import MetaAdsAdSetEdit, MetaAdsAdSetSetting
from ..tools.schemas.budgets import BID_STRATEGIES
from ..tools.schemas.objects import CLOSED_STATUSES, MetaAdsObject
from ..tools.utils.validation import absolute_date
from .create_ad_set import (
    BID_AMOUNT_STRATEGIES,
    LEGACY_ADVANTAGE_TYPES,
    bid_problem,
    includes_eu,
    spend_control_problems,
)
from .list_objects import NO_SPEND_CAP

MONEY_SETTINGS = frozenset(
    {"bid_amount", "min_daily_spend", "max_daily_spend", "min_lifetime_spend", "max_lifetime_spend"}
)
# Settings whose change Meta counts as significant, so learning starts again.
BID_SETTINGS = frozenset({"bid_strategy", "bid_amount", "min_roas"})
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
    }


def requested_values(edit: MetaAdsAdSetEdit) -> dict[MetaAdsAdSetSetting, str | None]:
    """The values the edit asks for; removing a limit or the end date asks for None."""
    return {
        key: None if getattr(edit, key) in ("remove", "none") else getattr(edit, key)
        for key in edit.settings
    }


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
            return ["The campaign sets the bid strategy for its ad sets, so change it there."]
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
    edit: MetaAdsAdSetEdit, *, currency: str, zone: ZoneInfo, now: datetime
) -> dict[str, str]:
    """Builds the update Meta receives: money in minor units and times in the account zone."""
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
    return body


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
