# apps/api/integrations/google_ads/tools/verifiers/campaign_budget.py

"""Live campaign-budget verification for Google Ads write tools."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_campaign_budgets import list_campaign_budgets
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
