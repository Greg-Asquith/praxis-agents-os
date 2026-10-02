# apps/api/integrations/meta_ads/entity_resolvers/ad.py

"""Meta Ads ad lookup for shared runtime entity selectors."""

from services.integrations.entity_references import EntityChoice, EntityResolverDefinition

from ..references import MetaAdsAdReference
from ..tools.schemas.objects import MetaAdsObject
from .utils import object_label, resolve_objects, search_objects, status_description


def ad_reference(entry, item: MetaAdsObject, _currency: str) -> MetaAdsAdReference | None:
    if item.campaign_id is None or item.adset_id is None:
        return None
    return MetaAdsAdReference(
        account_id=entry.external_id,
        campaign_id=item.campaign_id,
        adset_id=item.adset_id,
        ad_id=item.id,
        label=object_label(item, "(unnamed ad)"),
        description=status_description(item, "Ad"),
        scope_label=entry.display_name,
        status=item.status,
        effective_status=item.effective_status,
    )


def _choice(entry, item: MetaAdsObject, currency: str) -> EntityChoice | None:
    reference = ad_reference(entry, item, currency)
    return EntityChoice.from_reference(reference, icon="meta_ads") if reference else None


async def search_meta_ads_ads(ctx, search, _dependent_args, page_size, cursor):
    return await search_objects(
        ctx, search, object_type="ad", page_size=page_size, cursor=cursor, choice=_choice
    )


async def resolve_meta_ads_ads(ctx, values, _dependent_args):
    return await resolve_objects(
        ctx, values, object_type="ad", reference_type=MetaAdsAdReference, choice=_choice
    )


META_ADS_AD_RESOLVER = EntityResolverDefinition(
    entity_kind="meta_ads_ad",
    reference_type=MetaAdsAdReference,
    search=search_meta_ads_ads,
    resolve=resolve_meta_ads_ads,
    max_page_size=25,
    requires_active_context=True,
    provider_key="meta_ads",
)
