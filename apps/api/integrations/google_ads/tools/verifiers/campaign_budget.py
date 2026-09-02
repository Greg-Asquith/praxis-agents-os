# apps/api/integrations/google_ads/tools/verifiers/campaign_budget.py

"""Live campaign-budget verification for Google Ads write tools."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_campaign_budgets import list_campaign_budgets
from integrations.google_ads.operations.utils import nonnegative_int
from integrations.google_ads.references import GoogleAdsCampaignBudgetReference
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry


async def verify_campaign_budgets(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    budget_ids: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    normalized_ids = tuple(dict.fromkeys(budget_ids))
    if (
        not normalized_ids
        or len(normalized_ids) != len(budget_ids)
        or any(not value.isdigit() for value in normalized_ids)
    ):
        raise ModelRetry("Choose each available Google Ads campaign budget only once.")
    rows = await list_campaign_budgets(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        budget_ids=normalized_ids,
        limit=len(normalized_ids),
    )
    rows_by_id = {str(row.get("id", "")): row for row in rows}
    if set(rows_by_id) != set(normalized_ids):
        raise ModelRetry(
            "A selected Google Ads campaign budget is no longer available. "
            "Ask the user to choose it again."
        )
    return rows_by_id


def campaign_budget_reference_from_row(
    entry: ResolvedContextEntry,
    selected: GoogleAdsCampaignBudgetReference,
    row: Mapping[str, Any],
) -> GoogleAdsCampaignBudgetReference:
    """Builds a reusable budget reference from freshly verified provider state."""
    budget_id = str(row.get("id", "")).strip()
    if budget_id != selected.budget_id:
        raise ModelRetry("A selected Google Ads campaign budget changed during verification.")
    period = str(row.get("period", "")).strip()
    if period not in {"DAILY", "CUSTOM_PERIOD"}:
        raise ModelRetry(
            f"Campaign budget {selected.label!r} has an unsupported live budget period."
        )
    reference_count = nonnegative_int(row.get("referenceCount"))
    if reference_count is None:
        raise ModelRetry(
            f"Campaign budget {selected.label!r} has no valid live linked-campaign count."
        )
    currency_code = str(row.get("currencyCode", "")).strip()
    if not currency_code:
        raise ModelRetry(
            "The selected Google Ads account has no currency information. "
            "Refresh the connection and retry."
        )
    delivery_method = str(row.get("deliveryMethod", "")).strip()
    explicitly_shared = row.get("explicitlyShared")
    if not delivery_method or not isinstance(explicitly_shared, bool):
        raise ModelRetry(f"Campaign budget {selected.label!r} has incomplete live settings.")
    amount_micros = nonnegative_int(row.get("amountMicros"))
    total_amount_micros = nonnegative_int(row.get("totalAmountMicros"))
    selected_amount = amount_micros if period == "DAILY" else total_amount_micros
    if selected_amount is None:
        raise ModelRetry(f"Campaign budget {selected.label!r} has no valid live amount.")
    labels = row.get("campaignLabels", ())
    campaign_labels = (
        tuple(str(label)[:500] for label in labels if str(label).strip())[:50]
        if isinstance(labels, (list, tuple))
        else ()
    )
    return GoogleAdsCampaignBudgetReference(
        customer_id=entry.external_id,
        budget_id=budget_id,
        label=(str(row.get("name", "")).strip() or selected.label)[:500],
        description="Campaign budget",
        scope_label=entry.display_name,
        status=str(row.get("status", "")).strip() or None,
        period=period,
        delivery_method=delivery_method,
        amount_micros=amount_micros,
        total_amount_micros=total_amount_micros,
        explicitly_shared=explicitly_shared,
        reference_count=reference_count,
        currency_code=currency_code,
        campaign_labels=campaign_labels,
    )
