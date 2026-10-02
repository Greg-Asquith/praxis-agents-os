# apps/api/integrations/meta_ads/entity_resolvers/ad_set.py

"""Meta Ads ad set lookup for shared runtime entity selectors."""

from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from ..references import MetaAdsAdSetReference
from ..tools.schemas.objects import MetaAdsObject
from .utils import object_label, resolve_objects, search_objects, status_description


def ad_set_reference(entry, item: MetaAdsObject, currency: str) -> MetaAdsAdSetReference | None:
    if item.campaign_id is None:
        return None
    return MetaAdsAdSetReference(
        account_id=entry.external_id,
        campaign_id=item.campaign_id,
        adset_id=item.id,
        label=object_label(item, "(unnamed ad set)"),
        description=status_description(item, "Ad set"),
        scope_label=entry.display_name,
        status=item.status,
        effective_status=item.effective_status,
        objective=item.objective,
        optimization_goal=item.optimization_goal,
        destination_type=item.destination_type,
        promoted_object=item.promoted_object,
        placements=item.placements,
        is_dynamic_creative=item.is_dynamic_creative,
        budget=item.budget,
        currency=currency or None,
    )


def _choice(entry, item: MetaAdsObject, currency: str) -> EntityChoice | None:
    reference = ad_set_reference(entry, item, currency)
    return EntityChoice.from_reference(reference, icon="meta_ads") if reference else None


async def search_meta_ads_ad_sets(ctx, search, _dependent_args, page_size, cursor):
    return await search_objects(
        ctx, search, object_type="adset", page_size=page_size, cursor=cursor, choice=_choice
    )


async def resolve_meta_ads_ad_sets(ctx, values, _dependent_args):
    return await resolve_objects(
        ctx,
        values,
        object_type="adset",
        reference_type=MetaAdsAdSetReference,
        choice=_choice,
    )


META_ADS_AD_SET_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_ad_set",
    reference_type=MetaAdsAdSetReference,
    search=search_meta_ads_ad_sets,
    resolve=resolve_meta_ads_ad_sets,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
