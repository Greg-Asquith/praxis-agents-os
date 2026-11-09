# apps/api/integrations/google_ads/entity_resolvers/bidding_strategy.py

"""Google Ads portfolio bidding strategy lookup for shared runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.campaign_bidding import STRATEGY_NAMES
from integrations.google_ads.operations.list_bidding_strategies import (
    MAX_BIDDING_STRATEGY_LOOKUP,
    list_bidding_strategies,
)
from integrations.google_ads.operations.utils import nonnegative_int
from integrations.google_ads.references import GoogleAdsBiddingStrategyReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import group_scoped_references, search_scoped_entities

# Portfolio-only types the campaign strategy names don't cover.
_TYPE_NAMES = {**STRATEGY_NAMES, "TARGET_SPEND": "Maximise Clicks"}


def _choice(entry, strategy: Mapping[str, Any]) -> EntityChoice | None:
    strategy_id = str(strategy.get("id", "")).strip()
    status = str(strategy.get("status", "")).strip()
    if not strategy_id.isdigit() or status == "REMOVED":
        return None
    kind = str(strategy.get("type", "")).strip()
    count = nonnegative_int(strategy.get("campaignCount"))
    name = str(strategy.get("name", "")).strip() or "(unnamed bidding strategy)"
    described = _TYPE_NAMES.get(kind, kind.replace("_", " ").title() or "Portfolio strategy")
    if count is not None:
        described = f"{described} · {count} campaign{'' if count == 1 else 's'}"
    return EntityChoice.from_reference(
        GoogleAdsBiddingStrategyReference(
            customer_id=entry.external_id,
            bidding_strategy_id=strategy_id,
            label=name[:500],
            description=described,
            scope_label=entry.display_name,
            strategy_type=kind or None,
            campaign_count=count,
        ),
        icon="google_ads",
    )


async def _query(ctx, entry, **filters: Any) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
    )
    return await list_bidding_strategies(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry), **filters
    )


async def search_google_ads_bidding_strategies(ctx, search, _dependent_args, page_size, cursor):
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


async def resolve_google_ads_bidding_strategies(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsBiddingStrategyReference,
        max_references=MAX_BIDDING_STRATEGY_LOOKUP - 1,
    )
    for entry, references in grouped:
        ids = [reference.bidding_strategy_id for reference in references]
        rows = await _query(ctx, entry, bidding_strategy_ids=ids, limit=len(ids))
        choices.extend(choice for row in rows if (choice := _choice(entry, row)) is not None)
    return tuple(choices)


GOOGLE_ADS_BIDDING_STRATEGY_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_bidding_strategy",
    reference_type=GoogleAdsBiddingStrategyReference,
    search=search_google_ads_bidding_strategies,
    resolve=resolve_google_ads_bidding_strategies,
    max_page_size=25,
    max_exact_values=MAX_BIDDING_STRATEGY_LOOKUP - 1,
    requires_active_context=True,
    provider_key="google_ads",
)
