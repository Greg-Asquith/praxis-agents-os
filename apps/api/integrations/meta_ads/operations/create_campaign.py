# apps/api/integrations/meta_ads/operations/create_campaign.py

"""Create one campaign, paused unless asked: account checks, the request body, one send, then a read-back."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient, ad_account_path
from ..models import MetaAdsObjectBudget
from ..money import amount_to_minor
from ..throttle import ensure_account_available
from ..tools.schemas.budgets import BID_STRATEGIES
from ..tools.schemas.campaigns import OBJECTIVES, MetaAdsCreateCampaignRequest
from .create_objects import MetaAdsCreateEdge, MetaCreateLookup
from .object_run import ObjectRun, create_and_read_back
from .values import (
    bounded_string,
    minimum_budget_problem,
    money_value,
    numeric_value,
    require_currency,
)

OPERATION = "create_campaign"
CAMPAIGN_GROUP = "campaigns:create"
CAMPAIGN_KEY = "campaign"
_ACCOUNT_FIELDS = (
    "currency,timezone_name,account_status,min_daily_budget,min_campaign_group_spend_cap"
)
# Disabled, pending closure, and closed accounts can't take new campaigns.
_CLOSED_ACCOUNT_STATUSES = frozenset({2, 100, 101})


@dataclass(frozen=True, slots=True)
class CampaignAccount:
    """What the ad account says about money, time, and status at preparation."""

    currency: str
    timezone_name: str | None
    closed: bool
    # Daily budget minimum in the account currency, when Meta reports one.
    minimum: str | None
    # Smallest spending limit a campaign can have, when Meta reports one.
    minimum_spend_limit: str | None


async def read_campaign_account(client: MetaAdsClient, *, account_id: str) -> CampaignAccount:
    ensure_account_available(account_id, operation=OPERATION)
    raw = await client.graph_get(
        ad_account_path(account_id),
        params={"fields": _ACCOUNT_FIELDS},
        operation=OPERATION,
        policy=IntegrationRequestPolicy.READ,
        usage_account_id=account_id,
    )
    currency = require_currency(raw.get("currency"), operation=OPERATION)
    status = numeric_value(raw.get("account_status"), count=True, operation=OPERATION)
    return CampaignAccount(
        currency=currency,
        timezone_name=bounded_string(raw.get("timezone_name"), operation=OPERATION),
        closed=status in _CLOSED_ACCOUNT_STATUSES,
        minimum=money_value(raw.get("min_daily_budget"), currency, operation=OPERATION),
        minimum_spend_limit=money_value(
            raw.get("min_campaign_group_spend_cap"), currency, operation=OPERATION
        ),
    )


def account_problems(
    request: MetaAdsCreateCampaignRequest, account: CampaignAccount, days: int | None
) -> list[str]:
    """Checks the account is open and the amounts meet its minimums."""
    if account.closed:
        return ["This ad account is disabled or closed, so Meta can't create campaigns in it."]
    problems: list[str] = []
    budget = request.budget
    if budget.amount is not None:
        kind = "daily" if budget.mode == "campaign_daily" else "lifetime"
        problem = minimum_budget_problem(
            kind=kind,
            amount=budget.amount,
            minimum=account.minimum,
            days=days,
            currency=account.currency,
            subject="this ad account",
        )
        if problem:
            problems.append(problem)
    if (
        request.spend_limit is not None
        and account.minimum_spend_limit is not None
        and Decimal(request.spend_limit) < Decimal(account.minimum_spend_limit)
    ):
        problems.append(
            f"The smallest spending limit for this ad account is {account.minimum_spend_limit} "
            f"{account.currency}."
        )
    return problems


@dataclass(frozen=True, slots=True)
class PlannedCampaign:
    """A new campaign as ad set rules check it, before it exists."""

    objective: str
    budget: MetaAdsObjectBudget | None
    bid_strategy: str
    special_ad_categories: list[str]
    share_between_ad_sets: bool | None
    status: str = "PAUSED"


def planned_campaign(request: MetaAdsCreateCampaignRequest) -> PlannedCampaign:
    """Describes the campaign the request makes, so a launch can check its ad sets first."""
    budget = request.budget
    held = None
    if budget.amount is not None:
        kind = "daily" if budget.mode == "campaign_daily" else "lifetime"
        held = MetaAdsObjectBudget(kind=kind, amount=budget.amount, remaining=None)
    return PlannedCampaign(
        objective=OBJECTIVES[request.objective],
        budget=held,
        bid_strategy=BID_STRATEGIES[request.bid_strategy],
        special_ad_categories=[item.category.upper() for item in request.special_ad_categories],
        share_between_ad_sets=budget.share_between_ad_sets,
    )


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    """The approved campaign as Meta will receive it."""

    body: dict[str, str]
    intent_fields: dict[str, str]


def plan_campaign(
    request: MetaAdsCreateCampaignRequest,
    *,
    currency: str,
    start_time: str | None,
    end_time: str | None,
) -> CampaignPlan:
    """Builds the body and its evidence; created by auction, paused unless the request says active."""
    categories = [item.category.upper() for item in request.special_ad_categories]
    countries = sorted({code for item in request.special_ad_categories for code in item.countries})
    body = {
        "name": request.name,
        "objective": OBJECTIVES[request.objective],
        "status": request.status.upper(),
        "buying_type": "AUCTION",
        "special_ad_categories": json.dumps(categories),
        # Meta's default strategy needs a bid on every ad set, so the strategy is always sent.
        "bid_strategy": BID_STRATEGIES[request.bid_strategy],
    }
    if countries:
        body["special_ad_category_country"] = json.dumps(countries)
    budget = request.budget
    if budget.mode == "ad_set":
        # Meta requires this without a campaign budget and refuses it with one.
        body["is_adset_budget_sharing_enabled"] = (
            "true" if budget.share_between_ad_sets else "false"
        )
    elif budget.amount is not None:
        kind = "daily" if budget.mode == "campaign_daily" else "lifetime"
        body[f"{kind}_budget"] = str(amount_to_minor(budget.amount, currency))
    if request.spend_limit is not None:
        body["spend_cap"] = str(amount_to_minor(request.spend_limit, currency))
    if start_time:
        body["start_time"] = start_time
    if end_time:
        body["stop_time"] = end_time
    fields = {
        "key": CAMPAIGN_KEY,
        "objective": request.objective,
        "budget_mode": budget.mode,
        "currency": currency,
        "special_ad_categories": ",".join(categories) or "none",
    }
    for key in (
        "status",
        "bid_strategy",
        "daily_budget",
        "lifetime_budget",
        "is_adset_budget_sharing_enabled",
        "spend_cap",
        "start_time",
        "stop_time",
    ):
        if body.get(key):
            fields[key] = body[key]
    if countries:
        fields["special_ad_category_country"] = ",".join(countries)
    return CampaignPlan(body=body, intent_fields=fields)


@dataclass
class CampaignRun(ObjectRun):
    """What the one create proved."""

    action: ClassVar[str] = "create_campaign"
    edge: ClassVar[MetaAdsCreateEdge] = "campaigns"
    object_type: ClassVar[Literal["campaign", "adset"]] = "campaign"
    noun: ClassVar[str] = "campaign"
    key: ClassVar[str] = CAMPAIGN_KEY


async def create_campaign(
    client: MetaAdsClient, *, account_id: str, currency: str, plan: CampaignPlan
) -> CampaignRun:
    """Sends the create once, settles a lost reply by name, then reads the campaign back.

    Raises:
        asyncio.CancelledError: With a `ledger` attribute: unverified once the create was sent.
    """
    return await create_and_read_back(
        client,
        CampaignRun(dict(plan.intent_fields)),
        account_id=account_id,
        currency=currency,
        body=plan.body,
        operation=OPERATION,
        lookup=MetaCreateLookup(name=plan.body["name"], since=datetime.now(UTC)),
    )
