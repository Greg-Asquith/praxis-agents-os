# apps/api/integrations/google_ads/entity_resolvers/ad.py

"""Google Ads ad lookup for shared runtime entity selectors."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.operations.list_ads import MAX_AD_LOOKUP, ad_display_name, list_ads
from integrations.google_ads.references import GoogleAdsAdReference
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from .utils import group_scoped_references, search_scoped_entities


def _choice(entry, row: Mapping[str, Any]) -> EntityChoice | None:
    ad_group_ad, ad_group, campaign = (row.get(key) for key in ("adGroupAd", "adGroup", "campaign"))
    if not all(isinstance(value, Mapping) for value in (ad_group_ad, ad_group, campaign)):
        return None
    ad = ad_group_ad.get("ad")
    if not isinstance(ad, Mapping):
        return None
    ids = (str(campaign.get("id", "")), str(ad_group.get("id", "")), str(ad.get("id", "")))
    status = str(ad_group_ad.get("status", "")).strip()
    if not all(value.isdigit() for value in ids) or status == "REMOVED":
        return None
    campaign_id, ad_group_id, ad_id = ids
    ad_type = str(ad.get("type", "")).replace("_", " ").strip().capitalize() or "Ad"
    campaign_name = str(campaign.get("name", "")).strip() or "(unnamed campaign)"
    ad_group_name = str(ad_group.get("name", "")).strip() or "(unnamed ad group)"
    return EntityChoice.from_reference(
        GoogleAdsAdReference(
            customer_id=entry.external_id,
            campaign_id=campaign_id,
            ad_group_id=ad_group_id,
            ad_id=ad_id,
            label=ad_display_name(ad)[:500],
            description=f"{ad_type} · {status.title()}" if status else ad_type,
            scope_label=f"{campaign_name[:240]} · {ad_group_name[:240]}",
            status=status or None,
        ),
        icon="google_ads",
    )


async def _query(ctx, entry, **filters: Any) -> list[Mapping[str, Any]]:
    client = await google_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
    )
    return await list_ads(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry), **filters
    )


async def search_google_ads_ads(ctx, search, _dependent_args, page_size, cursor):
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


async def resolve_google_ads_ads(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(
        ctx, GOOGLE_ADS_BINDING, values, GoogleAdsAdReference, max_references=MAX_AD_LOOKUP - 1
    )
    for entry, references in grouped:
        wanted = {reference.provider_entity_id for reference in references}
        rows = await _query(
            ctx,
            entry,
            ad_ids=[reference.ad_id for reference in references],
            ad_group_ids=[reference.ad_group_id for reference in references],
            limit=MAX_AD_LOOKUP,
        )
        for row in rows:
            choice = _choice(entry, row)
            if (
                choice is not None
                and f"{choice.value['ad_group_id']}~{choice.value['ad_id']}" in wanted
            ):
                choices.append(choice)
    return tuple(choices)


GOOGLE_ADS_AD_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_ad",
    reference_type=GoogleAdsAdReference,
    search=search_google_ads_ads,
    resolve=resolve_google_ads_ads,
    max_page_size=25,
    max_exact_values=MAX_AD_LOOKUP - 1,
    requires_active_context=True,
    provider_key="google_ads",
)
