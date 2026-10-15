# apps/api/integrations/meta_ads/operations/create_ad_set.py

"""Create one paused ad set: campaign rules, the request body, one send, then a read-back."""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

from core.exceptions.integration import IntegrationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient, ad_account_path
from ..goals import GOALS
from ..models import MetaAdsObjectBudget, MetaAdsPlacements, MetaAdsPromotedObject
from ..money import amount_to_minor
from ..references import MetaAdsApplicationReference
from ..throttle import ensure_account_available
from ..tools.schemas.ad_sets import (
    MetaAdsAdSetPlacements,
    MetaAdsAdSetSettings,
    MetaAdsEuTransparency,
)
from ..tools.schemas.budgets import BID_STRATEGIES
from ..tools.schemas.objects import CLOSED_STATUSES, MetaAdsObject
from .ad_rows import ad_effect
from .create_objects import MetaCreateLookup, MetaCreateResult, create_object
from .list_objects import read_objects_by_id
from .mutations import MetaAdsMutationLedger, MetaAdsMutationParent
from .targeting import targeting_problems, targeting_spec
from .values import bounded_string, money_value, require_currency

OPERATION = "create_ad_set"
AD_SET_GROUP = "adsets:create"
AD_SET_KEY = "ad_set"
_ACCOUNT_FIELDS = (
    "currency,timezone_name,min_daily_budget,default_dsa_payor,default_dsa_beneficiary"
)
# Categories whose ads Meta limits to broad targeting.
_TARGETING_CATEGORIES = frozenset(
    {"HOUSING", "EMPLOYMENT", "FINANCIAL_PRODUCTS_SERVICES", "CREDIT"}
)
# EU member states and associated territories with their own country codes, for the DSA rule.
_EU_COUNTRIES = frozenset(
    {
        *("AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE"),
        *("IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"),
        *("AX", "GF", "GP", "MQ", "MF", "RE", "YT"),
    }
)
_STORE_HOSTS = {
    "google_play": ("play.google.com",),
    "app_store": ("apps.apple.com", "itunes.apple.com"),
}
_BID_AMOUNT_STRATEGIES = frozenset({"COST_CAP", "LOWEST_COST_WITH_BID_CAP"})
_EU_NAMES_MISSING = (
    "This ad set reaches people in the EU, so Meta needs who pays for the ads and who they "
    "benefit, and this ad account has no defaults. Ask the operator for eu_payer and "
    "eu_beneficiary; Meta shows both publicly in its ad library."
)
_READBACK_FAILED = "Meta Ads created this ad set, but it couldn't be read back."


class CampaignFacts(Protocol):
    """The campaign details an ad set is checked against, from a reference or a live read."""

    @property
    def status(self) -> str | None: ...
    @property
    def objective(self) -> str | None: ...
    @property
    def budget(self) -> MetaAdsObjectBudget | None: ...
    @property
    def bid_strategy(self) -> str | None: ...
    @property
    def special_ad_categories(self) -> list[str] | None: ...
    @property
    def share_between_ad_sets(self) -> bool | None: ...


def campaign_problems(request: MetaAdsAdSetSettings, campaign: CampaignFacts) -> list[str]:
    """Lists what this campaign won't take: goal, budget, bids, and targeting limits."""
    row = GOALS[request.goal]
    if campaign.status in CLOSED_STATUSES:
        return ["This campaign is archived or deleted."]
    if campaign.objective != row.objective:
        return [
            f"The goal {request.goal} needs a {_objective(row.objective)} campaign, and this "
            f"campaign is {_objective(campaign.objective)}. Choose a goal for its objective, "
            "or another campaign."
        ]
    problems = _budget_problems(request, campaign)
    problems.extend(_bid_problems(request, campaign))
    problems.extend(
        targeting_problems(request.targeting, special_category=special_category(campaign))
    )
    return problems


def special_category(campaign: CampaignFacts) -> bool:
    return bool(_TARGETING_CATEGORIES.intersection(campaign.special_ad_categories or ()))


def _objective(value: str | None) -> str:
    return (value or "unknown").removeprefix("OUTCOME_").replace("_", " ").lower()


def _budget_problems(request: MetaAdsAdSetSettings, campaign: CampaignFacts) -> list[str]:
    if campaign.budget is not None:
        if request.budget is not None:
            return ["This campaign holds the budget, so leave the ad set's budget out."]
        return []
    problems: list[str] = []
    if request.budget is None:
        problems.append("This campaign's ad sets hold their own budgets, so set a budget.")
    elif campaign.share_between_ad_sets and request.budget.kind != "daily":
        problems.append("This campaign's ad sets share budgets, so use a daily budget.")
    if request.min_daily_spend or request.max_daily_spend:
        problems.append("Daily spend limits apply only under a campaign budget.")
    return problems


def bid_strategy(request: MetaAdsAdSetSettings, campaign: CampaignFacts) -> str:
    """Meta's strategy for the ad set: the campaign's own, or the requested one."""
    requested = BID_STRATEGIES[request.bid_strategy or "highest_volume"]
    return campaign.bid_strategy or requested


def _bid_problems(request: MetaAdsAdSetSettings, campaign: CampaignFacts) -> list[str]:
    strategy = bid_strategy(request, campaign)
    if request.bid_strategy and BID_STRATEGIES[request.bid_strategy] != strategy:
        return ["The ad set follows its campaign's bid strategy, so leave bid_strategy out."]
    if strategy in _BID_AMOUNT_STRATEGIES and request.bid_amount is None:
        return ["This bid strategy needs a bid_amount on the ad set."]
    if strategy not in _BID_AMOUNT_STRATEGIES and request.bid_amount is not None:
        return ["This bid strategy doesn't take a bid_amount."]
    if (strategy == "LOWEST_COST_WITH_MIN_ROAS") != (request.min_roas is not None):
        return ["Set min_roas for a return on ad spend goal, and only for it."]
    return []


def reaches_eu(request: MetaAdsAdSetSettings) -> bool:
    countries = {
        location.key if location.kind == "country" else location.country_code
        for location in request.targeting.locations
    }
    countries.update(
        location.key.split(":", 1)[0]
        for location in request.targeting.locations
        if location.kind == "postcode"
    )
    return bool(_EU_COUNTRIES.intersection(countries))


@dataclass(frozen=True, slots=True)
class AdSetAccount:
    """What the ad account says about money, time, and EU defaults at preparation."""

    currency: str
    timezone_name: str | None
    # Daily minimum in the account currency for the goal's kind, when Meta reports one.
    minimum: str | None
    dsa_payor: str | None
    dsa_beneficiary: str | None


async def read_ad_set_account(
    client: MetaAdsClient, *, account_id: str, request: MetaAdsAdSetSettings
) -> AdSetAccount:
    ensure_account_available(account_id, operation=OPERATION)
    raw = await client.graph_get(
        ad_account_path(account_id),
        params={"fields": _ACCOUNT_FIELDS},
        operation=OPERATION,
        policy=IntegrationRequestPolicy.READ,
        usage_account_id=account_id,
    )
    currency = require_currency(raw.get("currency"), operation=OPERATION)
    minimum = await _goal_minimum(client, account_id, request, currency)
    return AdSetAccount(
        currency=currency,
        timezone_name=bounded_string(raw.get("timezone_name"), operation=OPERATION),
        minimum=minimum or money_value(raw.get("min_daily_budget"), currency, operation=OPERATION),
        dsa_payor=_dsa_name(raw.get("default_dsa_payor")),
        dsa_beneficiary=_dsa_name(raw.get("default_dsa_beneficiary")),
    )


async def _goal_minimum(
    client: MetaAdsClient, account_id: str, request: MetaAdsAdSetSettings, currency: str
) -> str | None:
    """Reads the goal's daily minimum; None when Meta reports none, so the account's applies."""
    kind = "high_freq" if request.pay_per_click else GOALS[request.goal].minimum
    try:
        payload = await client.graph_get(
            f"{ad_account_path(account_id)}/minimum_budgets",
            params={"fields": f"min_daily_budget_{kind}"},
            operation=OPERATION,
            policy=IntegrationRequestPolicy.READ,
            usage_account_id=account_id,
        )
    except IntegrationError:
        return None
    rows = payload.get("data")
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    try:
        return money_value(row.get(f"min_daily_budget_{kind}"), currency, operation=OPERATION)
    except IntegrationError:
        return None


def _dsa_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:512] or None


def eu_transparency(request: MetaAdsAdSetSettings, account: AdSetAccount) -> MetaAdsEuTransparency:
    """Decides how the EU names are given, or fails before the create when they can't be.

    Raises:
        ValueError: The ad set reaches the EU, and a name is neither given nor an account default.
    """
    if not reaches_eu(request):
        return "not_needed"
    if not (request.eu_payer or account.dsa_payor) or not (
        request.eu_beneficiary or account.dsa_beneficiary
    ):
        raise ValueError(_EU_NAMES_MISSING)
    return "sent" if request.eu_payer and request.eu_beneficiary else "account_defaults"


def minimum_problem(
    request: MetaAdsAdSetSettings, account: AdSetAccount, days: int | None
) -> str | None:
    """Checks the ad set's own budget against Meta's daily minimum for its goal."""
    if request.budget is None or account.minimum is None:
        return None
    minimum = Decimal(account.minimum)
    if request.budget.kind == "daily" and Decimal(request.budget.amount) < minimum:
        return f"The minimum daily budget for this goal is {account.minimum} {account.currency}."
    if (
        request.budget.kind == "lifetime"
        and days
        and Decimal(request.budget.amount) < minimum * days
    ):
        return (
            f"Over {days} days, the minimum lifetime budget for this goal is "
            f"{format(minimum * days, 'f')} {account.currency}."
        )
    return None


def store_url(app: MetaAdsApplicationReference, store: str) -> str | None:
    """Returns the app's page in the chosen store, from Meta's own store URLs."""
    hosts = _STORE_HOSTS[store]
    return next((url for url in app.store_urls if urlsplit(url).hostname in hosts), None)


@dataclass(frozen=True, slots=True)
class AdSetPlan:
    """The approved ad set as Meta will receive it."""

    body: dict[str, str]
    eu: MetaAdsEuTransparency
    intent_fields: dict[str, str]

    def with_campaign(self, campaign_id: str) -> "AdSetPlan":
        """Returns the plan with the campaign it goes in, in both the body and the evidence."""
        return AdSetPlan(
            body={**self.body, "campaign_id": campaign_id},
            eu=self.eu,
            intent_fields={**self.intent_fields, "campaign_id": campaign_id},
        )


def plan_ad_set(
    request: MetaAdsAdSetSettings,
    campaign: CampaignFacts,
    *,
    campaign_id: str | None,
    currency: str,
    start_time: str | None,
    end_time: str | None,
    eu: MetaAdsEuTransparency,
    object_store_url: str | None = None,
    key: str = AD_SET_KEY,
) -> AdSetPlan:
    """Builds the body and its text-free evidence; created paused, always.

    A launch plans its ad sets before the campaign exists, so `campaign_id` is None and
    the body gains it from `with_campaign` once the campaign is created.
    """
    row = GOALS[request.goal]
    targeting = targeting_spec(request.targeting)
    targeting.update(_placements(request.placements))
    body = {
        "name": request.name,
        "status": "PAUSED",
        "optimization_goal": row.optimization_goal,
        "billing_event": "LINK_CLICKS" if request.pay_per_click else "IMPRESSIONS",
        "targeting": json.dumps(targeting),
    }
    if row.destination_type:
        body["destination_type"] = row.destination_type
    if promoted := _promoted_object(request, object_store_url):
        body["promoted_object"] = json.dumps(promoted)
    body.update(_money(request, campaign, currency))
    if start_time:
        body["start_time"] = start_time
    if end_time:
        body["end_time"] = end_time
    if eu == "sent" and request.eu_payer and request.eu_beneficiary:
        body.update(dsa_payor=request.eu_payer, dsa_beneficiary=request.eu_beneficiary)
    plan = AdSetPlan(body=body, eu=eu, intent_fields=_intent_fields(request, body, eu, key))
    return plan.with_campaign(campaign_id) if campaign_id else plan


@dataclass(frozen=True, slots=True)
class PlannedAdSet:
    """A new ad set as ad creation checks it, before it exists."""

    objective: str
    optimization_goal: str
    destination_type: str | None
    promoted_object: MetaAdsPromotedObject | None
    placements: MetaAdsPlacements
    status: str = "PAUSED"
    is_dynamic_creative: bool = False


def planned_ad_set(request: MetaAdsAdSetSettings) -> PlannedAdSet:
    """Describes the ad set the settings make, so a launch can check its ads before approval."""
    row = GOALS[request.goal]
    promoted = _promoted_object(request, None)
    if request.app is not None:
        # The store page is read at preparation; ad checks only need the app.
        promoted = {"application_id": request.app.application_id}
    return PlannedAdSet(
        objective=row.objective,
        optimization_goal=row.optimization_goal,
        destination_type=row.destination_type,
        promoted_object=MetaAdsPromotedObject.model_validate(promoted) if promoted else None,
        placements=MetaAdsPlacements(
            mode=request.placements.mode, positions=list(request.placements.positions)
        ),
    )


def _placements(placements: MetaAdsAdSetPlacements) -> dict[str, Any]:
    # No placement fields means Meta's automatic placements.
    if placements.mode == "automatic":
        return {}
    spec: dict[str, Any] = {}
    for position in placements.positions:
        platform, name = position.split(":", 1)
        spec.setdefault("publisher_platforms", [])
        if platform not in spec["publisher_platforms"]:
            spec["publisher_platforms"].append(platform)
        spec.setdefault(f"{platform}_positions", []).append(name)
    devices = ["mobile", "desktop"] if placements.devices == "all" else [placements.devices]
    spec["device_platforms"] = devices
    return spec


def _promoted_object(
    request: MetaAdsAdSetSettings, object_store_url: str | None
) -> dict[str, str] | None:
    if request.page is not None:
        return {"page_id": request.page.page_id}
    if request.pixel is not None:
        if request.custom_conversion_id:
            return {
                "pixel_id": request.pixel.pixel_id,
                "custom_conversion_id": request.custom_conversion_id,
            }
        return {"pixel_id": request.pixel.pixel_id, "custom_event_type": request.conversion_event}
    if request.app is not None and object_store_url:
        return {"application_id": request.app.application_id, "object_store_url": object_store_url}
    return None


def _money(request: MetaAdsAdSetSettings, campaign: CampaignFacts, currency: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if request.budget is not None:
        values[f"{request.budget.kind}_budget"] = str(
            amount_to_minor(request.budget.amount, currency)
        )
    # With a campaign budget, or a campaign strategy, the ad set inherits the strategy.
    if campaign.budget is None and campaign.bid_strategy is None:
        values["bid_strategy"] = bid_strategy(request, campaign)
    if request.bid_amount is not None:
        values["bid_amount"] = str(amount_to_minor(request.bid_amount, currency))
    if request.min_roas is not None:
        floor = int(Decimal(request.min_roas) * 10_000)
        values["bid_constraints"] = json.dumps({"roas_average_floor": floor})
    if request.min_daily_spend is not None:
        values["daily_min_spend_target"] = str(amount_to_minor(request.min_daily_spend, currency))
    if request.max_daily_spend is not None:
        values["daily_spend_cap"] = str(amount_to_minor(request.max_daily_spend, currency))
    return values


def _intent_fields(
    request: MetaAdsAdSetSettings, body: Mapping[str, str], eu: MetaAdsEuTransparency, key: str
) -> dict[str, str]:
    """Records IDs, money in minor units, and targeting as keys and counts, never names."""
    targeting = request.targeting
    fields = {
        "key": key,
        "goal": request.goal,
        "status": "PAUSED",
        "locations": ",".join(f"{item.kind}:{item.key}" for item in targeting.locations),
        "excluded_locations": str(len(targeting.excluded_locations)),
        "ages": f"{targeting.age_min}-{targeting.age_max or '65+'}",
        "genders": targeting.genders,
        "detailed_items": str(sum(len(group) for group in targeting.detailed)),
        "audience_ids": ",".join(item.audience_id for item in targeting.audiences) or "none",
        "advantage_audience": "true" if targeting.advantage_audience else "false",
        "placements": request.placements.mode,
        "eu_transparency": eu,
    }
    for key in (
        "promoted_object",
        "daily_budget",
        "lifetime_budget",
        "bid_strategy",
        "bid_amount",
        "bid_constraints",
        "daily_min_spend_target",
        "daily_spend_cap",
        "billing_event",
        "start_time",
        "end_time",
    ):
        if body.get(key):
            fields[key] = body[key]
    return fields


@dataclass
class AdSetRun:
    """What the one create proved."""

    fields: dict[str, str]
    outcome: MetaCreateResult | None = None
    # Set once the create has been handed to Meta, so an interruption is unverified.
    sending: bool = False
    skip_code: str | None = None
    skip_message: str | None = None
    read: dict[str, Any] | None = None
    created: MetaAdsObject | None = None

    @property
    def enabled(self) -> frozenset[str]:
        return frozenset()

    def ledger(self) -> MetaAdsMutationLedger:
        return MetaAdsMutationLedger(
            action="create_ad_set",
            parents=(
                MetaAdsMutationParent(
                    identity=(("key", AD_SET_KEY),), decision="submit", effects=(ad_effect(self),)
                ),
            ),
        )


async def create_ad_set(
    client: MetaAdsClient, *, account_id: str, currency: str, plan: AdSetPlan
) -> AdSetRun:
    """Sends the create once, settles a lost reply by name, then reads the ad set back.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute: unverified once the create was sent.
    """
    run = AdSetRun(dict(plan.intent_fields))
    try:
        lookup = MetaCreateLookup(
            name=plan.body["name"],
            parent_field="campaign.id",
            parent_id=plan.body["campaign_id"],
            since=datetime.now(UTC),
        )
        run.sending = True
        run.outcome = await create_object(
            client,
            account_id=account_id,
            edge="adsets",
            data=plan.body,
            operation=OPERATION,
            lookup=lookup,
        )
        if (created_id := run.outcome.object_id) and run.outcome.status == "applied":
            await _read_back(client, account_id, currency, created_id, run)
    except (asyncio.CancelledError, Exception) as exc:
        exc.ledger = run.ledger()
        raise
    return run


async def _read_back(
    client: MetaAdsClient, account_id: str, currency: str, adset_id: str, run: AdSetRun
) -> None:
    try:
        found = await read_objects_by_id(
            client,
            account_id=account_id,
            object_type="adset",
            object_ids=[adset_id],
            currency=currency,
        )
    except IntegrationError:
        return
    if item := found.get(adset_id):
        run.created = item
        run.read = {"effective_status": item.effective_status}


def readback_message(run: AdSetRun) -> str | None:
    effect = ad_effect(run)
    if effect.outcome == "applied" and run.read is None:
        return _READBACK_FAILED
    return effect.message
