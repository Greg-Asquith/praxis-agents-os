# apps/api/integrations/google_ads/entity_resolvers/campaign_budget.py

"""Google Ads campaign budget lookup for runtime entity references."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_campaign_budgets import list_campaign_budgets
from integrations.google_ads.operations.utils import nonnegative_int
from integrations.google_ads.references import GoogleAdsCampaignBudgetReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import group_scoped_references, search_scoped_entities


def _choice(entry, budget: Mapping[str, Any]) -> EntityChoice | None:
    budget_id = str(budget.get("id", "")).strip()
    status = str(budget.get("status", "")).strip()
    if not budget_id.isdigit() or status == "REMOVED":
        return None
    name = str(budget.get("name", "")).strip() or "(unnamed campaign budget)"
    reference_count = nonnegative_int(budget.get("referenceCount"))
    description = (
        f"{reference_count} linked campaign{'s' if reference_count != 1 else ''}"
        if reference_count is not None
        else "Campaign budget"
    )
    labels = budget.get("campaignLabels", ())
    campaign_labels = (
        tuple(str(label)[:500] for label in labels if str(label).strip())[:50]
        if isinstance(labels, (list, tuple))
        else ()
    )
    return EntityChoice.from_reference(
        GoogleAdsCampaignBudgetReference(
            customer_id=entry.external_id,
            budget_id=budget_id,
            label=name[:500],
            description=description,
            scope_label=entry.display_name,
            status=status or None,
            period=str(budget.get("period", "")).strip() or None,
            delivery_method=str(budget.get("deliveryMethod", "")).strip() or None,
            amount_micros=nonnegative_int(budget.get("amountMicros")),
            total_amount_micros=nonnegative_int(budget.get("totalAmountMicros")),
            explicitly_shared=(
                budget.get("explicitlyShared")
                if isinstance(budget.get("explicitlyShared"), bool)
                else None
            ),
            reference_count=reference_count,
            currency_code=str(budget.get("currencyCode", "")).strip() or None,
            campaign_labels=campaign_labels,
        ),
        icon="google_ads",
    )


async def _query(
    ctx,
    entry,
    *,
    budget_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    return await list_campaign_budgets(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        budget_ids=budget_ids,
        search=search,
        minimum_id=minimum_id,
        minimum_id_inclusive=minimum_id_inclusive,
        limit=limit,
    )


async def search_google_ads_campaign_budgets(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip()

    async def query_entry(entry, minimum_id, _minimum_secondary_id, inclusive, limit):
        return await _query(
            ctx,
            entry,
            search=normalized_search or None,
            minimum_id=minimum_id,
            minimum_id_inclusive=inclusive,
            limit=limit,
        )

    return await search_scoped_entities(
        ctx,
        GOOGLE_ADS_BINDING,
        search=normalized_search,
        page_size=page_size,
        cursor=cursor,
        query_entry=query_entry,
        choice_for_row=_choice,
    )


async def resolve_google_ads_campaign_budgets(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsCampaignBudgetReference,
    )
    for entry, references in grouped:
        ids = [reference.budget_id for reference in references]
        budgets = await _query(ctx, entry, budget_ids=ids, limit=len(ids))
        choices.extend(
            choice for budget in budgets if (choice := _choice(entry, budget)) is not None
        )
    return tuple(choices)


GOOGLE_ADS_CAMPAIGN_BUDGET_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_campaign_budget",
    reference_type=GoogleAdsCampaignBudgetReference,
    search=search_google_ads_campaign_budgets,
    resolve=resolve_google_ads_campaign_budgets,
    max_page_size=25,
    requires_active_context=True,
    provider_key="google_ads",
)
