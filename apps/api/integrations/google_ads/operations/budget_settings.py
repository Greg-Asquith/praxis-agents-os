# apps/api/integrations/google_ads/operations/budget_settings.py

"""Reads the campaign budgets that `google_ads_update_budgets` changes, and what they spent."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import nonnegative_int, stream_rows

# Each budget setting's field path in Google's JSON names, as the edit seam compares and masks it.
AMOUNT_PATH = "amountMicros"
DELIVERY_PATH = "deliveryMethod"
# A campaign's budget, which moving it onto a shared budget changes.
CAMPAIGN_BUDGET_PATH = "campaignBudget"
# Campaigns read per request when listing the campaigns a budget funds.
MAX_BUDGET_CAMPAIGNS = 10_000
_BUDGET_NAME = re.compile(r"customers/\d+/campaignBudgets/\d+")
_BUDGET_FIELDS = (
    "campaign_budget.resource_name",
    "campaign_budget.id",
    "campaign_budget.name",
    "campaign_budget.status",
    "campaign_budget.period",
    "campaign_budget.amount_micros",
    "campaign_budget.delivery_method",
    "campaign_budget.explicitly_shared",
    "campaign_budget.reference_count",
)
_CAMPAIGN_FIELDS = (
    "campaign.resource_name",
    "campaign.id",
    "campaign.name",
    "campaign.status",
    "campaign.experiment_type",
    "campaign.campaign_budget",
)


@dataclass(frozen=True, slots=True)
class LiveBudget:
    resource_name: str
    name: str
    status: str
    # `DAILY`, or `CUSTOM_PERIOD` for a total over the campaign's run.
    period: str
    shared: bool
    # How many campaigns use the budget, removed ones included.
    reference_count: int
    # By setting path, as the edit seam compares them: micros as an int64 string.
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LiveCampaign:
    resource_name: str
    name: str
    status: str
    # `BASE` for a normal campaign; drafts and experiments keep their own budget.
    experiment_type: str
    budget: str
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class BudgetCampaign:
    """A campaign a budget funds, and its cost this month in micros."""

    resource_name: str
    name: str
    status: str
    budget: str
    cost_micros: int


async def read_campaigns(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
) -> dict[str, LiveCampaign]:
    """Returns each campaign and the budget it uses by resource name, removed ones included."""
    if not campaign_ids:
        return {}
    ids = _ids(campaign_ids)
    rows = await _search(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        query=f"SELECT {', '.join(_CAMPAIGN_FIELDS)} FROM campaign WHERE campaign.id IN ({ids})",  # noqa: S608 -- digits only
        operation="read_budget_campaigns",
        max_rows=len(set(campaign_ids)),
    )
    live: dict[str, LiveCampaign] = {}
    for row in rows:
        campaign = row.get("campaign")
        if not isinstance(campaign, Mapping) or not isinstance(campaign.get("resourceName"), str):
            continue
        budget = str(campaign.get(CAMPAIGN_BUDGET_PATH) or "")
        live[campaign["resourceName"]] = LiveCampaign(
            resource_name=campaign["resourceName"],
            name=str(campaign.get("name") or "Campaign"),
            status=str(campaign.get("status") or ""),
            experiment_type=str(campaign.get("experimentType") or ""),
            budget=budget,
            values={
                CAMPAIGN_BUDGET_PATH: budget or None,
                "resourceName": campaign["resourceName"],
                "status": campaign.get("status"),
            },
        )
    return live


async def read_budgets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    budget_ids: Sequence[str],
) -> dict[str, LiveBudget]:
    """Returns each budget by resource name, removed ones included."""
    if not budget_ids:
        return {}
    ids = _ids(budget_ids)
    rows = await _search(
        client,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        query=(
            f"SELECT {', '.join(_BUDGET_FIELDS)} FROM campaign_budget "  # noqa: S608 -- digits only
            f"WHERE campaign_budget.id IN ({ids})"
        ),
        operation="read_campaign_budgets",
        max_rows=len(set(budget_ids)),
    )
    live: dict[str, LiveBudget] = {}
    for row in rows:
        budget = row.get("campaignBudget")
        if not isinstance(budget, Mapping) or not isinstance(budget.get("resourceName"), str):
            continue
        amount = nonnegative_int(budget.get(AMOUNT_PATH))
        live[budget["resourceName"]] = LiveBudget(
            resource_name=budget["resourceName"],
            name=str(budget.get("name") or "Budget"),
            status=str(budget.get("status") or ""),
            period=str(budget.get("period") or ""),
            shared=budget.get("explicitlyShared") is True,
            reference_count=nonnegative_int(budget.get("referenceCount")) or 0,
            values={
                AMOUNT_PATH: str(amount) if amount is not None else None,
                DELIVERY_PATH: budget.get(DELIVERY_PATH),
                "resourceName": budget["resourceName"],
                "status": budget.get("status"),
            },
        )
    return live


async def read_budget_campaigns(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    budgets: Sequence[str],
) -> list[BudgetCampaign]:
    """Returns the campaigns that use each budget, with what each has cost this month.

    The month is the calendar month in the account time zone, as Google reports it.
    """
    if not budgets:
        return []
    names = ", ".join(f"'{_budget_name(item)}'" for item in sorted(set(budgets)))
    where = f"campaign.status != 'REMOVED' AND campaign.campaign_budget IN ({names})"
    query = (
        "SELECT campaign.resource_name, campaign.name, campaign.status, "  # noqa: S608 -- validated resource names
        f"campaign.campaign_budget FROM campaign WHERE {where}"
    )
    # A campaign with no cost this month has no metrics row, so its cost is read apart.
    cost_query = (
        "SELECT campaign.resource_name, metrics.cost_micros FROM campaign "  # noqa: S608 -- validated resource names
        f"WHERE {where} AND segments.date DURING THIS_MONTH"
    )
    kwargs = {"client": client, "customer_id": customer_id, "login_customer_id": login_customer_id}
    rows = await _search(
        **kwargs,
        query=query,
        operation="read_budget_campaigns",
        max_rows=MAX_BUDGET_CAMPAIGNS,
    )
    cost_rows = await _search(
        **kwargs,
        query=cost_query,
        operation="read_budget_campaign_costs",
        max_rows=MAX_BUDGET_CAMPAIGNS,
    )
    costs: dict[str, int] = {}
    for row in cost_rows:
        campaign, metrics = row.get("campaign"), row.get("metrics")
        if isinstance(campaign, Mapping) and isinstance(metrics, Mapping):
            name = str(campaign.get("resourceName") or "")
            costs[name] = costs.get(name, 0) + (nonnegative_int(metrics.get("costMicros")) or 0)
    campaigns: list[BudgetCampaign] = []
    for row in rows:
        campaign = row.get("campaign")
        if not isinstance(campaign, Mapping) or not isinstance(campaign.get("resourceName"), str):
            continue
        campaigns.append(
            BudgetCampaign(
                resource_name=campaign["resourceName"],
                name=str(campaign.get("name") or "Campaign"),
                status=str(campaign.get("status") or ""),
                budget=str(campaign.get(CAMPAIGN_BUDGET_PATH) or ""),
                cost_micros=costs.get(campaign["resourceName"], 0),
            )
        )
    return campaigns


def _ids(values: Sequence[str]) -> str:
    if not all(value.isdigit() for value in values):
        raise ValueError("Google Ads budget reads need numeric IDs")
    return ", ".join(sorted(set(values)))


def _budget_name(value: str) -> str:
    if _BUDGET_NAME.fullmatch(value) is None:
        raise ValueError("Google Ads budget reads need budget resource names")
    return value


async def _search(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    query: str,
    operation: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation=operation,
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return stream_rows(payload, max_rows=max_rows)
