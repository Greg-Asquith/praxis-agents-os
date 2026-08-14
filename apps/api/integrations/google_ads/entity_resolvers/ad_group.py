# apps/api/integrations/google_ads/entity_resolvers/ad_group.py

"""Google Ads ad-group lookup for shared runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.references import GoogleAdsAdGroupReference
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


def _choice(entry, row: Mapping[str, Any]) -> EntityChoice | None:
    ad_group = row.get("adGroup")
    campaign = row.get("campaign")
    if not isinstance(ad_group, Mapping) or not isinstance(campaign, Mapping):
        return None
    ad_group_id = str(ad_group.get("id", "")).strip()
    status = str(ad_group.get("status", "")).strip()
    if not ad_group_id.isdigit() or status == "REMOVED":
        return None
    name = str(ad_group.get("name", "")).strip() or "(unnamed ad group)"
    campaign_name = str(campaign.get("name", "")).strip() or "(unnamed campaign)"
    campaign_id = str(campaign.get("id", "")).strip()
    if not campaign_id.isdigit():
        return None
    return EntityChoice.from_reference(
        GoogleAdsAdGroupReference(
            customer_id=entry.external_id,
            campaign_id=campaign_id,
            ad_group_id=ad_group_id,
            label=name[:500],
            description=status.title() if status else "Ad group",
            scope_label=campaign_name[:500],
            status=status or None,
        ),
        icon="google_ads",
    )


async def _query(
    ctx,
    entry,
    *,
    ad_group_ids: Sequence[str] = (),
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
    return await list_ad_groups(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        ad_group_ids=ad_group_ids,
        search=search,
        minimum_id=minimum_id,
        minimum_id_inclusive=minimum_id_inclusive,
        limit=limit,
        exclude_removed=exclude_removed,
    )


async def search_google_ads_ad_groups(ctx, search, _dependent_args, page_size, cursor):
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


async def resolve_google_ads_ad_groups(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(ctx, GOOGLE_ADS_BINDING, values, GoogleAdsAdGroupReference)
    for entry, references in grouped:
        ids = [reference.ad_group_id for reference in references]
        rows = await _query(
            ctx,
            entry,
            ad_group_ids=ids,
            limit=len(ids),
            exclude_removed=True,
        )
        choices.extend(choice for row in rows if (choice := _choice(entry, row)) is not None)
    return tuple(choices)


GOOGLE_ADS_AD_GROUP_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_ad_group",
    reference_type=GoogleAdsAdGroupReference,
    search=search_google_ads_ad_groups,
    resolve=resolve_google_ads_ad_groups,
    max_page_size=25,
    requires_active_context=True,
    provider_key="google_ads",
)
