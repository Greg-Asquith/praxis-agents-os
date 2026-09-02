# apps/api/integrations/google_ads/operations/list_campaign_budgets.py

"""List Google Ads campaign budgets for lookup and live verification."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows


async def list_campaign_budgets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    budget_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Return active budgets with bounded linked-campaign labels."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > 101:
        raise ValueError("Google Ads campaign budget lookup limit must be between 1 and 101")
    if any(not budget_id.isdigit() for budget_id in budget_ids):
        raise ValueError("Google Ads campaign budget ids must contain only digits")
    normalized_ids = sorted(set(budget_ids))
    if len(normalized_ids) > 101:
        raise ValueError("Google Ads campaign budget lookup accepts at most 101 ids")

    filters = ["campaign_budget.status != 'REMOVED'"]
    if normalized_ids:
        filters.append(f"campaign_budget.id IN ({', '.join(normalized_ids)})")
    if search and search.strip():
        filters.append(f"campaign_budget.name LIKE '%{escape_gaql_like_literal(search.strip())}%'")
    if boundary_filter := entity_id_boundary_filter(
        "campaign_budget.id",
        minimum_id=minimum_id,
        inclusive=minimum_id_inclusive,
    ):
        filters.append(boundary_filter)
    query = (
        "SELECT campaign_budget.id, campaign_budget.name, campaign_budget.status, "  # noqa: S608 -- digit-only ids and escaped search
        "campaign_budget.period, campaign_budget.delivery_method, "
        "campaign_budget.amount_micros, campaign_budget.total_amount_micros, "
        "campaign_budget.explicitly_shared, campaign_budget.reference_count, "
        "customer.currency_code FROM campaign_budget "
        f"WHERE {' AND '.join(filters)} ORDER BY campaign_budget.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_campaign_budgets",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    budgets = [
        {**budget, "currencyCode": str(customer.get("currencyCode", ""))}
        for row in stream_rows(payload, max_rows=limit)
        if isinstance((budget := row.get("campaignBudget")), Mapping)
        and isinstance((customer := row.get("customer", {})), Mapping)
    ]
    if not budgets:
        return []
    labels = await _campaign_labels(
        client,
        customer_id=normalized_customer_id,
        login_customer_id=login_customer_id,
        budget_ids=[str(item.get("id", "")) for item in budgets],
    )
    return [
        {**budget, "campaignLabels": labels.get(str(budget.get("id", "")), ())}
        for budget in budgets
    ]


async def _campaign_labels(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    budget_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    resource_names = [
        f"'customers/{customer_id}/campaignBudgets/{budget_id}'"
        for budget_id in budget_ids
        if budget_id.isdigit()
    ]
    if not resource_names:
        return {}
    query = (
        "SELECT campaign.id, campaign.name, campaign.campaign_budget FROM campaign "  # noqa: S608 -- resource names contain only validated digit ids
        "WHERE campaign.status != 'REMOVED' AND campaign.campaign_budget IN "
        f"({', '.join(resource_names)}) ORDER BY campaign.id LIMIT 10000"
    )
    payload = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation="list_campaign_budget_campaigns",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    labels: dict[str, list[str]] = {}
    for row in stream_rows(payload, max_rows=10000):
        campaign = row.get("campaign")
        if not isinstance(campaign, Mapping):
            continue
        resource_name = str(campaign.get("campaignBudget", ""))
        budget_id = resource_name.rsplit("/", 1)[-1]
        name = str(campaign.get("name", "")).strip() or str(campaign.get("id", ""))
        if budget_id.isdigit() and name and len(labels.setdefault(budget_id, [])) < 50:
            labels[budget_id].append(name[:500])
    return {budget_id: tuple(values) for budget_id, values in labels.items()}
