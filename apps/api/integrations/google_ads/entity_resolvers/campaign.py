# apps/api/integrations/google_ads/entity_resolvers/campaign.py

"""Google Ads campaign lookup for shared runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
)

from .utils import group_scoped_references, search_scoped_entities


def _choice(entry, campaign: Mapping[str, Any]) -> EntityChoice | None:
    campaign_id = str(campaign.get("id", "")).strip()
    status = str(campaign.get("status", "")).strip()
    if not campaign_id.isdigit() or status == "REMOVED":
        return None
    name = str(campaign.get("name", "")).strip() or "(unnamed campaign)"
    return EntityChoice.from_reference(
        GoogleAdsCampaignReference(
            customer_id=entry.external_id,
            campaign_id=campaign_id,
            label=name[:500],
            description=status.title() if status else "Campaign",
            scope_label=entry.display_name,
            status=status or None,
        ),
        icon="google_ads",
    )


async def _query(
    ctx,
    entry,
    *,
    campaign_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
    exclude_removed: bool,
) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db,
        actor=ctx.actor,
        workspace=ctx.workspace,
        entry=entry,
    )
    return await list_campaigns(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=campaign_ids,
        search=search,
        minimum_id=minimum_id,
        minimum_id_inclusive=minimum_id_inclusive,
        limit=limit,
        exclude_removed=exclude_removed,
    )


async def search_google_ads_campaigns(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip()

    async def query_entry(entry, minimum_id, inclusive, limit):
        return await _query(
            ctx,
            entry,
            search=normalized_search or None,
            minimum_id=minimum_id,
            minimum_id_inclusive=inclusive,
            limit=limit,
            exclude_removed=True,
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


async def resolve_google_ads_campaigns(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(ctx, GOOGLE_ADS_BINDING, values, GoogleAdsCampaignReference)
    for entry, references in grouped:
        ids = [reference.campaign_id for reference in references]
        campaigns = await _query(
            ctx,
            entry,
            campaign_ids=ids,
            limit=len(ids),
            exclude_removed=True,
        )
        choices.extend(
            choice for campaign in campaigns if (choice := _choice(entry, campaign)) is not None
        )
    return tuple(choices)


GOOGLE_ADS_CAMPAIGN_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_campaign",
    reference_type=GoogleAdsCampaignReference,
    search=search_google_ads_campaigns,
    resolve=resolve_google_ads_campaigns,
    max_page_size=25,
    requires_active_context=True,
    provider_key="google_ads",
)
